"""Real Builder/campaign admission, with no live model calls or worker execution."""

import pytest

from tests.iterative_episode_refiner.conftest import campaign  # noqa: F401


@pytest.fixture
def observer_home(tmp_path, campaign):
    home = tmp_path / 'observer-profile'
    root = home / 'openchia'
    root.mkdir(parents=True)
    (root / 'authority.sqlite3').symlink_to(campaign.duets.path)
    (root / 'episode_runs').symlink_to(campaign.session.store.evidence.runs.root, target_is_directory=True)
    return home
