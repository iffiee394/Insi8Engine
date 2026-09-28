"""Gemini keys are tried in order and Claude is only the last resort (no real API calls)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import llm
import provider_state


class FakeModels:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    def generate_content(self, **kwargs):
        outcome = self.behaviour(kwargs["model"])
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome, usage_metadata=SimpleNamespace(total_token_count=42))


def fake_client_factory(per_key):
    def factory(api_key):
        return SimpleNamespace(models=FakeModels(per_key[api_key]))
    return factory


DAILY_429 = RuntimeError(
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota', "
    "'details': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}}"
)
BAD_KEY = RuntimeError("400 INVALID_ARGUMENT. {'error': {'message': 'API key not valid. Please pass a valid API key.'}}")


class ProviderChainTests(unittest.TestCase):
    def setUp(self):
        provider_state._state, provider_state._usage = {}, {}
        self.patches = [
            patch.object(provider_state, "_save", lambda: None),
            patch.object(llm.time, "sleep", lambda s: None),
            patch.object(llm.config, "GEMINI_FALLBACK_MODELS", []),
            patch.object(llm.config, "LLM_PRIMARY", "gemini"),
            patch.object(llm.config, "FALLBACK_TO_ANTHROPIC", True),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        provider_state._state = provider_state._usage = None

    def run_chain(self, per_key, anthropic="", claude_reply="from claude"):
        keys = [(f"gemini_{i + 1}", key) for i, key in enumerate(per_key)]
        with patch.object(provider_state, "gemini_keys", return_value=keys), \
             patch("google.genai.Client", side_effect=fake_client_factory(per_key)), \
             patch.object(llm.config, "ANTHROPIC_API_KEY", anthropic), \
             patch.object(llm, "_call_anthropic", return_value=claude_reply) as claude:
            return llm.call_deep_llm("prompt"), claude

    def test_quota_on_first_key_moves_to_second(self):
        text, claude = self.run_chain({"k1": lambda m: DAILY_429, "k2": lambda m: "from key 2"}, anthropic="a")
        self.assertEqual(text, "from key 2")
        claude.assert_not_called()
        self.assertIn("daily quota", provider_state.blocked_reason("gemini_1", llm.config.GEMINI_CHAT_MODEL))

    def test_exhausted_key_is_skipped_next_time_without_a_call(self):
        calls = []
        def k1(model):
            calls.append(model)
            return DAILY_429
        self.run_chain({"k1": k1, "k2": lambda m: "ok"})
        self.run_chain({"k1": k1, "k2": lambda m: "ok"})
        self.assertEqual(len(calls), 1)

    def test_claude_only_after_every_gemini_key_fails(self):
        text, claude = self.run_chain(
            {"k1": lambda m: DAILY_429, "k2": lambda m: BAD_KEY, "k3": lambda m: DAILY_429}, anthropic="a",
        )
        self.assertEqual(text, "from claude")
        claude.assert_called_once()

    def test_model_missing_on_one_account_moves_to_next_key(self):
        retired = RuntimeError("404 NOT_FOUND. {'error': {'message': 'This model is no longer available to new users.'}}")
        text, claude = self.run_chain(
            {"k1": lambda m: DAILY_429, "k2": lambda m: retired, "k3": lambda m: "from key 3"}, anthropic="a",
        )
        self.assertEqual(text, "from key 3")
        claude.assert_not_called()

    def test_all_failing_gives_a_readable_step_by_step_error(self):
        with self.assertRaises(llm.ProviderChainError) as ctx:
            self.run_chain({"k1": lambda m: DAILY_429, "k2": lambda m: BAD_KEY})
        message = str(ctx.exception)
        self.assertTrue(message.startswith("All AI providers failed"))
        self.assertIn("Gemini key 1: daily quota used up", message)
        self.assertIn("Gemini key 2: key rejected by Google", message)
        self.assertEqual(llm.friendly_llm_error(ctx.exception), message)


if __name__ == "__main__":
    unittest.main()
