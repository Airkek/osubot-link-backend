import importlib
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi.testclient import TestClient

import app
import settings
from servers import OAuthServer


def provider(name):
    return OAuthServer(
        name, 'osu!' if name == 'bancho' else 'Morasooma',
        'https://osu.ppy.sh' if name == 'bancho' else 'https://morasooma.net',
        '42' if name == 'bancho' else '79', name + '-secret',
        'https://osulink.keijia.cyou/callback/' + name,
        's link' if name == 'bancho' else 'm link',
        'osu_link_state' if name == 'bancho' else 'morasooma_link_state',
    )


class LinkApiTests(unittest.TestCase):
    def setUp(self):
        self.providers = {name: provider(name) for name in ['bancho', 'morasooma']}
        self.patcher = patch.dict(app.SERVERS, self.providers, clear=True)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = TestClient(app.APP, base_url='https://link.test')
        self.addCleanup(self.client.close)

    def authorize(self, server):
        response = self.client.get('/auth', params={'server': server}, follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        return parse_qs(urlsplit(response.headers['location']).query)['state'][0]

    def test_server_list_and_selected_landing_page(self):
        self.assertEqual(self.client.get('/api/servers').json(), {'servers': ['bancho', 'morasooma']})
        page = self.client.get('/link?server=morasooma')
        self.assertEqual(page.status_code, 200)
        self.assertIn('/auth?server=morasooma', page.text)
        self.assertNotIn('/auth?server=bancho', page.text)
        self.assertIn('Morasooma', page.text)

    def test_missing_morasooma_credentials_disable_all_its_routes(self):
        app.SERVERS['morasooma'] = replace(self.providers['morasooma'], client_secret='')
        self.assertEqual(self.client.get('/api/servers').json(), {'servers': ['bancho']})
        self.assertNotIn('Morasooma', self.client.get('/link').text)
        for path in ['/link?server=morasooma', '/auth?server=morasooma', '/callback/morasooma', '/api/verify?server=morasooma&code=ABCDEFGH']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, follow_redirects=False).status_code, 404)

    def test_no_credentials_are_safe_to_import_and_report_as_unconfigured(self):
        for name in app.SERVERS:
            app.SERVERS[name] = replace(app.SERVERS[name], client_id='')
        self.assertEqual(self.client.get('/api/servers').json(), {'servers': []})
        self.assertEqual(self.client.get('/link').status_code, 503)

    def test_authorization_uses_each_providers_exact_callback_and_cookie(self):
        for name, server in self.providers.items():
            with self.subTest(server=name):
                response = self.client.get('/auth', params={'server': name}, follow_redirects=False)
                url = urlsplit(response.headers['location'])
                self.assertEqual(url.scheme + '://' + url.netloc, server.base_url)
                query = parse_qs(url.query)
                self.assertEqual(query['redirect_uri'], [server.redirect_url])
                self.assertEqual(query['client_id'], [server.client_id])
                self.assertEqual(query['scope'], ['identify'])
                cookie = response.headers['set-cookie']
                for value in [server.state_cookie, 'HttpOnly', 'Secure', 'SameSite=lax']:
                    self.assertIn(value, cookie)
        default = self.client.get('/auth', follow_redirects=False)
        self.assertTrue(default.headers['location'].startswith('https://osu.ppy.sh/oauth/authorize?'))

    def test_callback_only_calls_the_selected_provider_and_creates_a_scoped_code(self):
        for name, server in self.providers.items():
            with self.subTest(server=name):
                state = self.authorize(name)
                oauth = AsyncMock()
                oauth.__aenter__.return_value = oauth
                oauth.post.return_value = httpx.Response(200, json={'access_token': 'test-token'}, request=httpx.Request('POST', server.base_url + '/oauth/token'))
                oauth.get.return_value = httpx.Response(200, json={'id': 130, 'username': 'player', 'is_restricted': True}, request=httpx.Request('GET', server.base_url + '/api/v2/me'))
                with patch('app.httpx.AsyncClient', return_value=oauth), patch('app.create_link_code', new_callable=AsyncMock, return_value='ABCDEFGH') as create:
                    response = self.client.get('/callback/' + name, params={'code': 'oauth-code', 'state': state})
                self.assertEqual(response.status_code, 200)
                self.assertIn(server.bot_command + ' ABCDEFGH', response.text)
                self.assertIsNone(self.client.cookies.get(server.state_cookie))
                create.assert_awaited_once_with('130', True, server=name)
                oauth.post.assert_awaited_once_with(server.base_url + '/oauth/token', json={
                    'grant_type': 'authorization_code', 'client_id': server.client_id,
                    'client_secret': server.client_secret, 'redirect_uri': server.redirect_url, 'code': 'oauth-code',
                })
                oauth.get.assert_awaited_once_with(server.base_url + '/api/v2/me', headers={'Authorization': 'Bearer test-token', 'x-api-version': '20241130'})

    def test_missing_mismatched_and_cross_server_state_never_exchange_codes(self):
        state = self.authorize('morasooma')
        cases = [
            ('/callback/morasooma', {'code': 'oauth-code'}),
            ('/callback/morasooma', {'code': 'oauth-code', 'state': 'wrong'}),
            ('/callback/bancho', {'code': 'oauth-code', 'state': state, 'server': 'morasooma'}),
        ]
        for path, query in cases:
            with self.subTest(path=path, query=query), patch('app.httpx.AsyncClient') as oauth, patch('app.create_link_code', new_callable=AsyncMock) as create:
                self.assertEqual(self.client.get(path, params=query).status_code, 400)
                oauth.assert_not_called()
                create.assert_not_awaited()
        self.client.cookies.clear()
        with patch('app.httpx.AsyncClient') as oauth:
            self.assertEqual(self.client.get('/callback/morasooma', params={'code': 'oauth-code', 'state': state}).status_code, 400)
            oauth.assert_not_called()

    def test_wrong_server_and_reused_codes_are_rejected_without_losing_a_valid_code(self):
        unused = True
        async def consume(code, server='bancho'):
            nonlocal unused
            if code != 'ABCDEFGH' or server != 'morasooma' or not unused:
                return None
            unused = False
            return '130', False
        with patch('app.consume_link_code', side_effect=consume):
            self.assertEqual(self.client.get('/api/verify?code=ABCDEFGH').status_code, 404)
            correct = self.client.get('/api/verify?code=ABCDEFGH&server=morasooma')
            self.assertEqual(correct.json(), {'server': 'morasooma', 'user_id': '130', 'is_restrict': False})
            self.assertEqual(self.client.get('/api/verify?code=ABCDEFGH&server=morasooma').status_code, 404)

    def test_legacy_verify_defaults_to_bancho(self):
        with patch('app.consume_link_code', new_callable=AsyncMock, return_value=('42', True)) as consume:
            response = self.client.get('/api/verify?code=ABCDEFGH')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'server': 'bancho', 'user_id': '42', 'is_restrict': True})
        consume.assert_awaited_once_with('ABCDEFGH', server='bancho')

    def test_invalid_provider_and_missing_code_do_not_touch_storage(self):
        with patch('app.consume_link_code', new_callable=AsyncMock) as consume:
            self.assertEqual(self.client.get('/api/verify?code=ABCDEFGH&server=unknown').status_code, 404)
            self.assertEqual(self.client.get('/api/verify?server=bancho').status_code, 400)
            consume.assert_not_awaited()


class SettingsTests(unittest.TestCase):
    def test_callback_paths_and_optional_redirect_base(self):
        with patch.dict('os.environ', {'OSU_OAUTH_REDIRECT_URL_BASE': 'https://osulink.keijia.cyou/'}, clear=True):
            importlib.reload(settings)
            self.assertEqual(settings.OSU_REDIRECT_URL, 'https://osulink.keijia.cyou/callback/bancho')
            self.assertEqual(settings.MORASOOMA_REDIRECT_URL, 'https://osulink.keijia.cyou/callback/morasooma')
            self.assertEqual(settings.MORASOOMA_CLIENT_ID, '')
        importlib.reload(settings)
