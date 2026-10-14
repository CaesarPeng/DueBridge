"""Detached, project-bound workers shared by CLI and MCP."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from .config import Config, load
from . import evidence, service, storage

_children: dict[str, subprocess.Popen] = {}
TERMINAL = {"completed", "partial", "failed", "interrupted"}


def _path(config: Config, job_id: str, suffix=".json") -> Path:
    if not re.fullmatch(r"job_[0-9a-f]{32}", job_id):
        raise ValueError("无效任务编号")
    return evidence.safe_cache(config, f".homework/jobs/{job_id}{suffix}")


def start(config: Config, kind: str, source_id: str | None = None, engine: str | None = None,
          timeout: int | None = None, include_all: bool = True) -> dict:
    if kind not in {"refresh", "scan", "inspect"}:
        raise ValueError("未知任务类型")
    if kind in {"refresh", "inspect"}:
        service.validate_refresh(config, source_id, engine, timeout)
    if kind == "inspect" and source_id is None:
        raise ValueError("结构检查需要指定一个来源")
    service.prepare_state(config)
    job_id = "job_" + uuid.uuid4().hex
    data = {"id": job_id, "kind": kind, "status": "queued", "created_at": storage.stamp(config),
            "updated_at": storage.stamp(config), "events": [], "parameters": {
                "source_id": source_id, "engine": engine, "timeout": timeout, "include_all": include_all}}
    storage.write_json(_path(config, job_id), data)
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent)
                   + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")}
    try:
        with _path(config, job_id, ".log").open("wb") as log:
            os.chmod(log.name, 0o600)
            process = subprocess.Popen([sys.executable, "-m", "homework_assistant.worker", str(config.root),
                                        job_id], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       env=environment, start_new_session=os.name != "nt")
        _children[job_id] = process
        storage.write_json(_path(config, job_id, ".pid.json"), {"pid": process.pid})
    except OSError as error:
        data.update(status="failed", message=str(error), updated_at=storage.stamp(config))
        storage.write_json(_path(config, job_id), data)
    return get(config, job_id)


def get(config: Config, job_id: str) -> dict:
    data = storage.read_json(_path(config, job_id))
    if not data:
        raise ValueError("该项目没有这个任务")
    if data["status"] not in TERMINAL:
        process = _children.get(job_id)
        pid = data.get("pid") or storage.read_json(_path(config, job_id, ".pid.json"), {}).get("pid")
        alive = True
        if process is not None:
            alive = process.poll() is None
        elif pid:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                alive = False
            except PermissionError:
                pass
        if not alive:
            # Only the worker writes job state. A read reports interruptions but
            # never races a final worker update by overwriting its state file.
            data = storage.read_json(_path(config, job_id))
            if data["status"] not in TERMINAL:
                data = {**data, "status": "interrupted", "message": "采集进程已退出；旧资料保留，可重新启动任务"}
    return {k: v for k, v in data.items() if k not in {"parameters", "pid"}}


def run_worker(root: Path, job_id: str) -> int:
    config = load(root)
    path = _path(config, job_id)
    data = storage.read_json(path)
    if not data or data["status"] != "queued":
        raise ValueError("任务不存在或已启动，不能重复执行")
    data.update(status="running", pid=os.getpid(), updated_at=storage.stamp(config))
    storage.write_json(path, data)

    def report(event):
        item = {**event, "at": storage.stamp(config)}
        data["last_progress"] = item
        data["events"] = (data["events"] + [item])[-100:]
        data["status"] = "waiting_for_user" if event.get("phase") == "waiting_for_user" else "running"
        data["updated_at"] = storage.stamp(config)
        storage.write_json(path, data)

    try:
        parameters = data["parameters"]
        if data["kind"] == "scan":
            result = service.scan_materials(config, parameters["include_all"], report)
        elif data["kind"] == "refresh":
            result = service.refresh(config, parameters["source_id"], parameters["engine"], parameters["timeout"], report)
        elif data["kind"] == "inspect":
            result = service.inspect_source(config, parameters["source_id"], parameters["engine"], parameters["timeout"], report)
        else:
            raise ValueError("未知任务类型")
        data.update(status="partial" if result["status"] == "partial" else "completed", result=result)
        code = result.get("exit_code", 0)
    except Exception as error:
        data.update(status="failed", message=f"{type(error).__name__}: {error}")
        code = 1
    finally:
        data["updated_at"] = storage.stamp(config)
        storage.write_json(path, data)
    return code
