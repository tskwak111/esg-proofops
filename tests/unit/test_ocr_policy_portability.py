"""Offline policy discovery must not require a paid POSIX spend-lock backend."""

import subprocess
import sys
import textwrap


def test_offline_readers_import_without_fcntl():
    script = textwrap.dedent("""        import importlib.abc
        import sys

        class NoFcntl(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "fcntl":
                    raise ModuleNotFoundError("simulated Windows: no fcntl")

        sys.meta_path.insert(0, NoFcntl())
        from proofops.adapters.local import claim_source_policies
        from proofops.adapters.local.upstage_ocr_page import PageOCRStore, reader_policy

        assert reader_policy()["profile"] == "upstage-ocr-page-v1"
        for profile in ("upstage-ocr-page-v1", "upstage-ocr-page-v2",
                        "upstage-ocr-page-v3", "upstage-ocr-page-v4", "upstage-ocr-page-v5"):
            reader = claim_source_policies.page_ocr_profile(profile)
            policy = reader.claim_source_policy()
            assert claim_source_policies.claim_source_reader(policy) is reader
        # A missing lock backend must still refuse funded dispatch before mutation.
        try:
            PageOCRStore._reserve(object(), None, None, None, False)
        except ModuleNotFoundError as error:
            assert "no fcntl" in str(error)
        else:
            raise AssertionError("Paid OCR must not bypass its shared spend lock")
    """)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
