import os

import pytest

from youtube_live_recorder.services.power import ES_CONTINUOUS, ES_SYSTEM_REQUIRED, PowerManager


@pytest.mark.windows
@pytest.mark.skipif(os.name != "nt", reason="Windows 전원 API 검증")
def test_real_windows_execution_state_sets_and_clears_system_only():
    power = PowerManager()
    try:
        power.set_required(True)
        assert power.required
        previous = power.setter(ES_CONTINUOUS)
        assert previous & ES_SYSTEM_REQUIRED
        assert not previous & 0x00000002  # 모니터 유지 플래그는 사용하지 않는다.
    finally:
        power.close()
    assert not power.required
