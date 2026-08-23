import os
from unittest.mock import patch

import pytest

from config.config import get_choice_default


SETTING = "TEST_PRODUCTION_HISTORIAN_OWNER"
ALLOWED = {"legacy_opc_service", "opc_tag_manager"}


def configured_owner() -> str:
    return get_choice_default(SETTING, ALLOWED, "legacy_opc_service")


def test_historian_owner_defaults_to_legacy_when_absent():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop(SETTING, None)
        assert configured_owner() == "legacy_opc_service"


@pytest.mark.parametrize("owner", ["legacy_opc_service", "opc_tag_manager"])
def test_historian_owner_accepts_supported_values(owner):
    with patch.dict(os.environ, {SETTING: owner}):
        assert configured_owner() == owner


def test_historian_owner_rejects_invalid_value_deterministically():
    with patch.dict(os.environ, {SETTING: "another_writer"}):
        with pytest.raises(
            RuntimeError,
            match=(
                "Configuration TEST_PRODUCTION_HISTORIAN_OWNER must be one of: "
                "legacy_opc_service, opc_tag_manager"
            ),
        ):
            configured_owner()
