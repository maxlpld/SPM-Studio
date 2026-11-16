"""Regression coverage for beginner Pi model selection and ChatGPT OAuth."""
from pathlib import Path

from spm_studio.ai import pi_setup

ROOT = Path(__file__).resolve().parents[1]


def models(provider, *names):
    return [{'provider': provider, 'id': name} for name in names]


def test_chatgpt_oauth_ignores_api_only_gpt4_and_selects_listed_models():
    offered = models('openai', 'gpt-4', 'gpt-5.4-codex', 'gpt-5.4-codex-mini', 'gpt-6-sol')
    options = pi_setup.recommend_answering_models(offered, {'openai': 'oauth'})
    assert options['fast'][0] == ('openai', 'gpt-5.4-codex-mini')
    assert options['smart'][0] == ('openai', 'gpt-6-sol')
    assert options['router'] is True
    assert all(name != 'gpt-4' for tier in ('fast', 'smart')
               for _, name in options[tier])


def test_chatgpt_oauth_without_compatible_models_does_not_guess():
    options = pi_setup.recommend_answering_models(
        models('openai', 'gpt-4', 'gpt-4o'), {'openai': 'oauth'})
    assert options == {'fast': [], 'smart': [], 'router': False}


def test_single_subscription_model_disables_routing():
    options = pi_setup.recommend_answering_models(
        models('openai', 'gpt-6-sol'), {'openai': 'oauth'})
    assert options['fast'][0] == options['smart'][0]
    assert options['router'] is False


def test_subscription_preferred_to_metered_key_and_only_signed_in_models():
    offered = (models('openai', 'gpt-5.4-codex', 'gpt-4')
               + models('anthropic', 'claude-4')
               + models('google', 'gemini-3'))
    options = pi_setup.recommend_answering_models(
        offered, {'openai': 'oauth', 'anthropic': 'api_key'})
    assert options['smart'][0][0] == 'openai'
    assert all(provider != 'google' for tier in ('fast', 'smart')
               for provider, _ in options[tier])


def test_api_key_provider_can_select_older_models_when_entitled():
    options = pi_setup.recommend_answering_models(
        models('openai', 'gpt-4'), {'openai': 'api_key'})
    assert options['fast'][0] == ('openai', 'gpt-4')


def test_wizard_requires_successful_smoke_test_before_finish():
    source = (ROOT / 'src/spm_studio/ai/pi_wizard.py').read_text(encoding='utf-8')
    assert '4: self._test_ok' in source
    assert 'self._test_ok = bool(ok)' in source
    assert 'Use recommended setup' in source
    assert 'def _on_model_edited' in source


def test_chatgpt_login_uses_current_openai_provider():
    assert ('openai', 'ChatGPT Plus / Pro (Sign in with ChatGPT)',
            '/login openai') in pi_setup.SUBSCRIPTIONS
