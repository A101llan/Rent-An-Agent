"""Pure schema/seed-manifest tests (no database fixtures)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.agents import AgentManifest, CreateVersionRequest, RuntimeRequirement
from app.scripts.seed import DEMO_AGENTS, build_manifest

AGENTS_DIR = Path(__file__).resolve().parents[3] / "agents"

LOCAL_RUNTIME = {"type": "local", "entrypoint": "meeting-notes", "min_sidecar_version": "0.1.0"}
DOCKER_RUNTIME = {"type": "docker", "image": "agenthub/x", "digest": "sha256:abc"}


def _version_request(manifest: dict, **extra) -> dict:
    return {"manifest": manifest, "price_minor": 100, **extra}


def test_docker_runtime_requires_image_and_digest():
    with pytest.raises(ValidationError):
        RuntimeRequirement.model_validate({"type": "docker", "image": "agenthub/x"})
    with pytest.raises(ValidationError):
        RuntimeRequirement.model_validate({"digest": "sha256:abc"})  # type defaults to docker
    assert not RuntimeRequirement.model_validate(DOCKER_RUNTIME).is_local


def test_docker_runtime_rejects_local_only_fields():
    with pytest.raises(ValidationError):
        RuntimeRequirement.model_validate({**DOCKER_RUNTIME, "entrypoint": "meeting-notes"})


def test_local_runtime_needs_no_image():
    runtime = RuntimeRequirement.model_validate(LOCAL_RUNTIME)
    assert runtime.is_local
    assert runtime.image is None and runtime.digest is None
    assert RuntimeRequirement.model_validate({"type": "local"}).is_local


def test_runtime_type_match_is_exact():
    # Only the lowercase string "local" skips the image requirement.
    with pytest.raises(ValidationError):
        RuntimeRequirement.model_validate({"type": "Local"})


def test_create_version_local_without_image():
    req = CreateVersionRequest.model_validate(_version_request({"runtime": LOCAL_RUNTIME}))
    assert req.image_name is None and req.image_digest is None
    dumped = req.manifest.model_dump(exclude_unset=True)
    assert dumped["runtime"] == LOCAL_RUNTIME


def test_create_version_server_still_requires_image():
    for manifest in ({"runtime": DOCKER_RUNTIME}, {}):
        with pytest.raises(ValidationError):
            CreateVersionRequest.model_validate(_version_request(manifest))
        with pytest.raises(ValidationError):
            CreateVersionRequest.model_validate(_version_request(manifest, image_name="agents/x"))
        req = CreateVersionRequest.model_validate(
            _version_request(manifest, image_name="agents/x", image_digest="sha256:abc")
        )
        assert req.image_digest == "sha256:abc"


def test_create_version_server_manifest_dump_unchanged():
    req = CreateVersionRequest.model_validate(
        _version_request({"runtime": DOCKER_RUNTIME}, image_name="agents/x", image_digest="sha256:abc")
    )
    assert req.manifest.model_dump(exclude_unset=True)["runtime"] == DOCKER_RUNTIME


@pytest.mark.parametrize("path", sorted(AGENTS_DIR.glob("*/manifest*.json")), ids=lambda p: p.parent.name + "/" + p.name)
def test_agent_manifest_files_validate(path: Path):
    AgentManifest.model_validate(json.loads(path.read_text(encoding="utf-8-sig")))


def test_meeting_notes_local_manifest_file():
    data = json.loads((AGENTS_DIR / "meeting-notes-agent" / "manifest.local.json").read_text(encoding="utf-8-sig"))
    assert data["runtime"]["type"] == "local"
    assert "image" not in data["runtime"] and "digest" not in data["runtime"]


def test_seed_manifests_validate_for_all_agents():
    slugs = {a["slug"] for a in DEMO_AGENTS}
    assert {"meeting-notes-agent", "meeting-notes-agent-local"} <= slugs
    for agent_data in DEMO_AGENTS:
        manifest = build_manifest(agent_data)
        runtime = manifest["runtime"]
        if agent_data["slug"] == "meeting-notes-agent-local":
            assert runtime["type"] == "local"
            assert "image" not in runtime
        else:
            assert runtime["type"] == "docker"
            assert runtime["image"] and runtime["digest"]


def _local_manifest_file_runtime() -> dict:
    path = AGENTS_DIR / "meeting-notes-agent" / "manifest.local.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))["runtime"]


def _local_agent_data() -> dict:
    return next(a for a in DEMO_AGENTS if a["slug"] == "meeting-notes-agent-local")


def test_seeded_local_runtime_equals_manifest_local_json():
    file_runtime = _local_manifest_file_runtime()
    assert file_runtime == {"type": "local", "entrypoint": "meeting-notes", "min_sidecar_version": "0.1.0"}
    assert build_manifest(_local_agent_data())["runtime"] == file_runtime
    # The one-off script seeds the same entry.
    from app.scripts.seed_meeting_notes_agent import AGENT_LOCAL

    assert build_manifest(AGENT_LOCAL)["runtime"] == file_runtime


def test_seed_reads_manifest_local_json_and_fallback_matches():
    from app.scripts import seed

    assert seed.MEETING_NOTES_LOCAL_MANIFEST_PATH is not None
    assert seed.MEETING_NOTES_LOCAL_MANIFEST_PATH.is_file()
    assert seed.load_meeting_notes_local_runtime() == _local_manifest_file_runtime()
    assert seed.MEETING_NOTES_LOCAL_RUNTIME_FALLBACK == _local_manifest_file_runtime()


class _FakeResult:
    def __init__(self, obj):
        self.obj = obj

    def scalar_one_or_none(self):
        return self.obj


class _FakeDb:
    def __init__(self, version):
        self.version = version

    async def execute(self, _stmt):
        return _FakeResult(self.version)


async def test_refresh_manifest_updates_stale_local_row_idempotently():
    from app.models import Agent, AgentVersion
    from app.scripts.seed_meeting_notes_agent import AGENT_LOCAL, refresh_manifest

    stale = build_manifest(AGENT_LOCAL)
    stale["runtime"] = {"type": "local", "entrypoint": "meeting-notes"}
    version = AgentVersion(version="1.0.0", manifest=stale)
    db = _FakeDb(version)
    agent = Agent(slug=AGENT_LOCAL["slug"])

    assert await refresh_manifest(db, agent, AGENT_LOCAL) is True
    assert version.manifest["runtime"] == _local_manifest_file_runtime()
    assert await refresh_manifest(db, agent, AGENT_LOCAL) is False  # second run: no-op
