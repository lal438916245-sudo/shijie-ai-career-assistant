"""零网络、只读的 Demo Replay 快照加载器。"""

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

import paths
from competition_contracts import CompetitionSnapshot


class ReplayManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int
    scenario_id: str
    title: str
    mode: str
    bundle_file: str
    bundle_sha256: str
    disclosure: str


DEFAULT_SCENARIO_DIR = Path(paths.DEMO_REPLAY_DIR) / "scenario_01"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_demo_replay(scenario_dir=None) -> CompetitionSnapshot:
    """读取并校验一个预存快照；不实例化 Agent、不访问数据库或网络。"""
    root = Path(scenario_dir or DEFAULT_SCENARIO_DIR).resolve()
    manifest_path = root / "manifest.json"
    manifest = ReplayManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8"))
    if manifest.mode != "demo_replay":
        raise ValueError("Replay manifest 必须明确声明 mode=demo_replay")

    bundle_path = (root / manifest.bundle_file).resolve()
    if root not in bundle_path.parents:
        raise ValueError("Replay bundle 路径越界")
    if _sha256(bundle_path) != manifest.bundle_sha256:
        raise ValueError("Replay bundle 校验和不匹配")

    snapshot = CompetitionSnapshot.model_validate_json(
        bundle_path.read_text(encoding="utf-8"))
    if snapshot.meta.mode != "demo_replay":
        raise ValueError("快照不是 Demo Replay 数据")
    if snapshot.meta.scenario_id != manifest.scenario_id:
        raise ValueError("manifest 与快照的 scenario_id 不一致")
    return snapshot

