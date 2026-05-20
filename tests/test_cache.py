"""Tests for cache strategy."""

from glm_summarizer.cache import CacheSession, _guess_language
from glm_summarizer.templates import PromptTemplate


SAMPLE_TEMPLATE = PromptTemplate(
    name="test",
    description="test template",
    system="You are a helpful coding assistant.",
    user="Review:\n```{language}\n{code}\n```\nFile: {path}",
)


class TestCacheSession:
    def test_session_has_id(self):
        s = CacheSession()
        assert len(s.id) == 32
        assert s._request_count == 0

    def test_build_messages_structure(self):
        s = CacheSession()
        msgs = s.build_messages(
            SAMPLE_TEMPLATE,
            code="def foo(): pass",
            path="test.py",
            language="python",
        )
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == SAMPLE_TEMPLATE.system
        assert msgs[1]["role"] == "user"
        assert "def foo(): pass" in msgs[1]["content"]
        assert "test.py" in msgs[1]["content"]
        assert s._request_count == 1

    def test_prefix_stability_tracking(self):
        s = CacheSession()
        s.build_messages(SAMPLE_TEMPLATE, code="x=1", path="a.py")
        assert s.is_stable

        # Different template with different system prompt
        other = PromptTemplate(
            name="other",
            description="",
            system="A different system prompt.",
            user="{code}",
        )
        s.build_messages(other, code="x=2", path="b.py")
        assert not s.is_stable
        assert len(s._warnings) == 1

    def test_same_template_stays_stable(self):
        s = CacheSession()
        for i in range(5):
            s.build_messages(SAMPLE_TEMPLATE, code=f"x={i}", path=f"f{i}.py")
        assert s.is_stable
        assert s._request_count == 5

    def test_stats(self):
        s = CacheSession()
        s.build_messages(SAMPLE_TEMPLATE, code="x=1", path="a.py")
        st = s.stats()
        assert st["requests"] == 1
        assert st["prefix_stable"] is True
        assert len(st["session_id"]) == 32


class TestLanguageGuessing:
    def test_common_extensions(self):
        assert _guess_language("foo.py") == "python"
        assert _guess_language("foo.js") == "javascript"
        assert _guess_language("foo.ts") == "typescript"
        assert _guess_language("foo.go") == "go"
        assert _guess_language("foo.rs") == "rust"
        assert _guess_language("foo.java") == "java"
        assert _guess_language("foo.cpp") == "cpp"
        assert _guess_language("foo.rb") == "ruby"
        assert _guess_language("foo.sh") == "bash"

    def test_unknown_extension(self):
        assert _guess_language("foo.xyz") == ""
        assert _guess_language("") == ""
