"""Tests for the LLM provider abstraction layer."""

import json
import os
import unittest
from unittest import mock

from beancount.ai.provider import OllamaProvider
from beancount.ai.provider import _extract_json
from beancount.ai.provider import get_provider


class TestExtractJson(unittest.TestCase):
    def test_plain_json(self):
        text = '{"key": "value"}'
        result = _extract_json(text)
        self.assertEqual(result, {"key": "value"})

    def test_json_with_markdown_fences(self):
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json(text)
        self.assertEqual(result, {"key": "value"})

    def test_json_with_plain_fences(self):
        text = '```\n{"key": 42}\n```'
        result = _extract_json(text)
        self.assertEqual(result, {"key": 42})

    def test_json_with_whitespace(self):
        text = '  \n  {"key": "value"}  \n  '
        result = _extract_json(text)
        self.assertEqual(result, {"key": "value"})


class TestGetProvider(unittest.TestCase):
    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            get_provider("nonexistent")

    @mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False)
    def test_auto_detect_anthropic(self):
        # Remove OPENAI key if present to ensure deterministic detection.
        env = {"ANTHROPIC_API_KEY": "test-key"}
        with mock.patch.dict(os.environ, env, clear=True):
            provider = get_provider()
            self.assertEqual(type(provider).__name__, "AnthropicProvider")

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True)
    def test_auto_detect_openai(self):
        provider = get_provider()
        self.assertEqual(type(provider).__name__, "OpenAIProvider")

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_auto_detect_fallback_ollama(self):
        provider = get_provider()
        self.assertEqual(type(provider).__name__, "OllamaProvider")

    def test_explicit_ollama(self):
        provider = get_provider("ollama")
        self.assertIsInstance(provider, OllamaProvider)

    def test_explicit_ollama_custom_model(self):
        provider = get_provider("ollama", model="mistral")
        self.assertEqual(provider.model, "mistral")

    def test_openai_requires_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                get_provider("openai")

    def test_anthropic_requires_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                get_provider("anthropic")


if __name__ == "__main__":
    unittest.main()
