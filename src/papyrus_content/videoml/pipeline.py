from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from papyrus_content.env import load_dotenv
from papyrus_content.papyrus_config import resolve_openai_api_key, resolve_openai_tts_defaults

from .config import SUPPORTED_VOICEOVER_PROVIDERS, VideoConfig
from .dsl import resolve_dsl_for_render

VIDEOML_CLI_ENV = "VIDEOML_CLI"
LOCAL_CLI_RELATIVE_PATH = Path("node_modules") / ".bin" / "vml"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


def output_mp4_path(config: VideoConfig, slug: str, theme: str = "dark") -> Path:
    config.scene_theme(theme)
    suffix = "-light" if theme == "light" else ""
    return config.output_dir / f"{slug}{suffix}.mp4"


def work_dir_for(config: VideoConfig, slug: str) -> Path:
    return config.work_dir / slug


def resolve_video_voiceover_provider(config: VideoConfig, explicit: str | None = None) -> str:
    if explicit:
        normalized = explicit.strip().lower()
        if normalized not in SUPPORTED_VOICEOVER_PROVIDERS:
            raise ValueError(
                f"Unsupported voiceover provider '{explicit}'. Supported: {', '.join(SUPPORTED_VOICEOVER_PROVIDERS)}"
            )
        return normalized
    return config.tts_provider


def resolve_voiceover_defaults(provider: str) -> dict[str, str]:
    if provider == "openai":
        defaults = resolve_openai_tts_defaults()
        return {"voice": str(defaults["voice"]), "model": str(defaults["model"])}
    raise ValueError(f"Unsupported voiceover provider '{provider}'.")


def ensure_browser_bundle(config: VideoConfig) -> Path:
    if not config.browser_bundle.is_file():
        raise ValueError(
            f"VideoML browser bundle is missing at {config.browser_bundle}. "
            "Build it with the publication's bundle script (see docs/video-pipeline.md)."
        )
    return config.browser_bundle


def resolve_vml_command(
    config: VideoConfig,
    dsl_path: Path,
    project_dir: Path,
    target_mp4: Path,
    environ: dict[str, str] | None = None,
) -> tuple[list[str], Path]:
    env = environ if environ is not None else os.environ
    pipeline_arguments = ["pipeline", str(dsl_path), "--project-dir", str(project_dir), "--out", str(target_mp4)]
    explicit = str(env.get(VIDEOML_CLI_ENV) or "").strip()
    if explicit:
        explicit_path = Path(explicit)
        if not explicit_path.is_file():
            raise ValueError(f"{VIDEOML_CLI_ENV} points at {explicit_path}, which is not a file.")
        launcher = ["node", str(explicit_path)] if explicit_path.suffix == ".js" else [str(explicit_path)]
        return launcher + pipeline_arguments, config.root
    if (config.root / LOCAL_CLI_RELATIVE_PATH).exists():
        return ["npx", "--no-install", "vml"] + pipeline_arguments, config.root
    raise ValueError(
        f"Could not find the VideoML CLI. Set {VIDEOML_CLI_ENV} to the vml executable, or add "
        f"@videoml/cli as a devDependency of the publication and run npm install in {config.root}."
    )


def build_vml_env(config: VideoConfig, provider: str) -> dict[str, str]:
    load_dotenv()
    env = os.environ.copy()
    env["BABULUS_BROWSER_BUNDLE"] = str(config.browser_bundle)
    if provider != "openai":
        raise ValueError(f"Unsupported voiceover provider '{provider}'.")
    api_key = resolve_openai_api_key()
    if not api_key:
        raise ValueError(
            "OpenAI API key is required. Set OPENAI_API_KEY or openai.api_key in .papyrus/config.yaml "
            "(use PAPYRUS_CONFIG to point at a config file from a worktree)."
        )
    env["OPENAI_API_KEY"] = api_key
    base_url = resolve_openai_tts_defaults().get("baseUrl")
    if base_url:
        env["OPENAI_BASE_URL"] = str(base_url)
    return env


def materialize_videoml_provider_config(project_dir: Path, *, provider: str) -> None:
    if provider != "openai":
        raise ValueError(f"Unsupported voiceover provider '{provider}'.")
    defaults = resolve_openai_tts_defaults()
    provider_config: dict[str, str] = {"voice": str(defaults["voice"]), "model": str(defaults["model"])}
    if defaults.get("baseUrl"):
        provider_config["base_url"] = str(defaults["baseUrl"])
    config_dir = project_dir / ".videoml"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yml").write_text(
        yaml.safe_dump({"providers": {"openai": provider_config}}, sort_keys=False), encoding="utf-8"
    )


def probe_openai_key() -> dict[str, Any]:
    load_dotenv()
    api_key = resolve_openai_api_key()
    if not api_key:
        raise ValueError("OpenAI API key is missing. Set OPENAI_API_KEY or openai.api_key in .papyrus/config.yaml.")
    defaults = resolve_openai_tts_defaults()
    request_body = json.dumps({"model": defaults["model"], "input": "ok", "voice": defaults["voice"]}).encode("utf-8")
    base_url = str(defaults.get("baseUrl") or DEFAULT_OPENAI_BASE_URL).rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/audio/speech",
        data=request_body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read(64)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ValueError(f"OpenAI TTS probe failed ({error.code}): {detail}") from error
    except urllib.error.URLError as error:
        raise ValueError(f"OpenAI TTS probe failed: {error}") from error
    return {
        "ok": True,
        "provider": "openai",
        "model": defaults["model"],
        "voice": defaults["voice"],
        "contentType": content_type,
        "bytesRead": len(body),
    }


def probe_voiceover_provider(provider: str) -> dict[str, Any]:
    if provider == "openai":
        return probe_openai_key()
    raise ValueError(f"Unsupported voiceover provider '{provider}'.")


def render_dsl_to_mp4(
    config: VideoConfig,
    *,
    dsl_path: Path,
    dsl_xml: str,
    project_dir: Path,
    target_mp4: Path,
    provider: str,
) -> Path:
    ensure_browser_bundle(config)
    command, command_cwd = resolve_vml_command(config, dsl_path, project_dir, target_mp4)
    environment = build_vml_env(config, provider)
    target_mp4.parent.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)
    dsl_path.write_text(dsl_xml, encoding="utf-8")
    materialize_videoml_provider_config(project_dir, provider=provider)
    result = subprocess.run(
        command,
        cwd=str(command_cwd),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "VideoML render failed.\n"
            f"command: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    if not target_mp4.exists():
        raise RuntimeError(f"VideoML reported success but output file is missing: {target_mp4}")
    return target_mp4


def render_video(
    config: VideoConfig,
    client: Any,
    slug: str,
    *,
    theme: str = "dark",
    from_article: bool = False,
    provider: str,
) -> Path:
    if not slug:
        raise ValueError("A slug is required for video rendering.")
    project_dir = work_dir_for(config, slug)
    dsl_xml = resolve_dsl_for_render(
        client=client,
        config=config,
        target_slug=slug,
        theme=theme,
        from_article=from_article,
        voiceover_defaults=resolve_voiceover_defaults,
        provider=provider,
    )
    return render_dsl_to_mp4(
        config,
        dsl_path=project_dir / f"{slug}-{theme}.babulus.xml",
        dsl_xml=dsl_xml,
        project_dir=project_dir,
        target_mp4=output_mp4_path(config, slug, theme),
        provider=provider,
    )
