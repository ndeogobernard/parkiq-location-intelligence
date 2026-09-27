# -*- coding: utf-8 -*-
"""ParkIQ Python toolbox for ArcGIS Pro (ADR-0016).

Each tool validates its parameters in ArcGIS Pro, then runs the ParkIQ command line in the
ParkIQ Python environment (not Pro's), so the analysis code and its dependencies stay in one
place. Output of the command is streamed to the geoprocessing messages.

Tools: Check Market Configuration, Run Pipeline Steps, Export File Geodatabase,
Build Portfolio Report.
"""

import os
import re
import subprocess
from pathlib import Path

import arcpy

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON = os.environ.get("PARKIQ_PYTHON", r"C:\GIS\envs\parkiq\python.exe")
STEPS = [
    "schema", "setup", "ingest", "qaqc", "demand", "supply", "gap",
    "screen", "walksheds", "criteria", "suitability", "sensitivity",
]
RUN_ID = re.compile(r"^\d{8}_\d{4}_[a-z0-9_]+_[A-Za-z]+$")


def _python_param():
    p = arcpy.Parameter(
        displayName="ParkIQ Python (parkiq environment)", name="parkiq_python",
        datatype="DEFile", parameterType="Optional", direction="Input",
    )
    p.value = DEFAULT_PYTHON
    p.category = "Environment"
    return p


def _market_param():
    p = arcpy.Parameter(
        displayName="Market file (markets/<slug>.yaml)", name="market",
        datatype="DEFile", parameterType="Required", direction="Input",
    )
    p.filter.list = ["yaml", "yml"]
    default = REPO / "markets" / "franklin_oh.yaml"
    if default.exists():
        p.value = str(default)
    return p


def _run_param(required):
    return arcpy.Parameter(
        displayName="Run ID (YYYYMMDD_HHMM_<market>_<scenario>)", name="run_id",
        datatype="GPString", parameterType="Required" if required else "Optional",
        direction="Input",
    )


def _check_common(params):
    """Shared validation: market file, ParkIQ python, run id pattern."""
    by = {p.name: p for p in params}
    m = by.get("market")
    if m is not None and m.value and not Path(str(m.valueAsText)).exists():
        m.setErrorMessage("Market file not found.")
    py = by.get("parkiq_python")
    if py is not None and py.value and not Path(str(py.valueAsText)).exists():
        py.setErrorMessage("ParkIQ Python not found; set PARKIQ_PYTHON or browse to python.exe.")
    r = by.get("run_id")
    if r is not None and r.value and not RUN_ID.match(str(r.valueAsText)):
        r.setErrorMessage("Run IDs look like 20260925_2217_franklin_oh_Balanced.")


def _run_cli(params, args):
    by = {p.name: p for p in params}
    exe = by["parkiq_python"].valueAsText or DEFAULT_PYTHON
    cmd = [exe, "-m", "parkiq.cli", *args]
    arcpy.AddMessage("Running: " + " ".join(cmd))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.Popen(
        cmd, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for line in proc.stdout:  # type: ignore[union-attr]
        line = line.rstrip()
        if line and "Warning" not in line:
            arcpy.AddMessage(line)
    rc = proc.wait()
    if rc != 0:
        arcpy.AddError(f"ParkIQ command failed (exit {rc}); see the messages above.")
        raise arcpy.ExecuteError


class Toolbox:
    def __init__(self):
        self.label = "ParkIQ"
        self.alias = "parkiq"
        self.tools = [CheckConfig, RunSteps, ExportGDB, BuildReport]


class CheckConfig:
    def __init__(self):
        self.label = "Check Market Configuration"
        self.description = "Validate a market file and list steps blocked by open (DECIDE) values."
        self.canRunInBackground = True

    def getParameterInfo(self):
        return [_market_param(), _python_param()]

    def updateMessages(self, parameters):
        _check_common(parameters)

    def execute(self, parameters, messages):
        _run_cli(parameters, ["check-config", "-m", parameters[0].valueAsText])


class RunSteps:
    def __init__(self):
        self.label = "Run Pipeline Steps"
        self.description = "Run ParkIQ steps (for example demand, supply, gap, screen) for a market."
        self.canRunInBackground = True

    def getParameterInfo(self):
        steps = arcpy.Parameter(
            displayName="Steps", name="steps", datatype="GPString",
            parameterType="Required", direction="Input", multiValue=True,
        )
        steps.filter.type = "ValueList"
        steps.filter.list = STEPS
        force = arcpy.Parameter(
            displayName="Re-run steps even if inputs are unchanged", name="force",
            datatype="GPBoolean", parameterType="Optional", direction="Input",
        )
        force.value = False
        return [_market_param(), steps, _run_param(False), force, _python_param()]

    def updateMessages(self, parameters):
        _check_common(parameters)
        steps = parameters[1]
        if steps.values:
            chosen = [str(v) for v in steps.values]
            order = [s for s in STEPS if s in chosen]
            if chosen != order:
                steps.setWarningMessage("Steps run in pipeline order: " + ", ".join(order))
            if not parameters[2].value and chosen and chosen[0] not in ("schema", "setup"):
                parameters[2].setWarningMessage(
                    "No run ID: a new run is started, and later steps need the earlier ones."
                )

    def execute(self, parameters, messages):
        chosen = [str(v) for v in parameters[1].values]
        args = ["run", "-m", parameters[0].valueAsText, "--steps", ",".join(s for s in STEPS if s in chosen)]
        if parameters[2].value:
            args += ["--run-id", parameters[2].valueAsText]
        if parameters[3].value:
            args.append("--force")
        _run_cli(parameters, args)


class ExportGDB:
    def __init__(self):
        self.label = "Export File Geodatabase"
        self.description = (
            "Export a run GeoPackage to a file geodatabase with domains, subtypes and "
            "relationship classes, next to the GeoPackage."
        )
        self.canRunInBackground = True

    def getParameterInfo(self):
        raw = arcpy.Parameter(
            displayName="Include raw source snapshots", name="raw", datatype="GPBoolean",
            parameterType="Optional", direction="Input",
        )
        raw.value = False
        return [_market_param(), _run_param(True), raw, _python_param()]

    def updateMessages(self, parameters):
        _check_common(parameters)

    def execute(self, parameters, messages):
        args = ["export-gdb", "-m", parameters[0].valueAsText, "--run-id", parameters[1].valueAsText]
        if parameters[2].value:
            args.append("--raw")
        _run_cli(parameters, args)


class BuildReport:
    def __init__(self):
        self.label = "Build Portfolio Report"
        self.description = "Build a report PDF from docs/portfolio/<slug>.md with numbers from a run."
        self.canRunInBackground = True

    def getParameterInfo(self):
        src = arcpy.Parameter(
            displayName="Report source (docs/portfolio/*.md)", name="source",
            datatype="DEFile", parameterType="Required", direction="Input",
        )
        src.filter.list = ["md"]
        out = arcpy.Parameter(
            displayName="Output PDF", name="out", datatype="DEFile",
            parameterType="Required", direction="Output",
        )
        out.filter.list = ["pdf"]
        title = arcpy.Parameter(
            displayName="Running header", name="short_title", datatype="GPString",
            parameterType="Optional", direction="Input",
        )
        return [_market_param(), _run_param(True), src, out, title, _python_param()]

    def updateMessages(self, parameters):
        _check_common(parameters)

    def execute(self, parameters, messages):
        args = [
            "report-pdf", "-m", parameters[0].valueAsText, "--run-id", parameters[1].valueAsText,
            "--source", parameters[2].valueAsText, "--out", parameters[3].valueAsText,
        ]
        if parameters[4].value:
            args += ["--short-title", parameters[4].valueAsText]
        _run_cli(parameters, args)
