import io
import os
import sys
import tempfile
import subprocess
import typing_extensions
import tarfile
import pathlib
import typer
import shutil
import rich
from probe_py.generated.parser import parse_probe_log
from probe_py.manual import analysis
from probe_py.manual import util

rich.traceback.install(show_locals=False)


project_root = pathlib.Path(__file__).resolve().parent.parent.parent.parent

A = typing_extensions.Annotated

app = typer.Typer()

def transcribe(probe_dir: pathlib.Path, output: pathlib.Path, debug: bool = False) -> None:
    """
    Transcribe the recorded data from PROBE_DIR into OUTPUT.
    """
    probe_log_tar_obj = tarfile.open(name=str(output), mode="x:gz")
    probe_log_tar_obj.add(probe_dir, arcname="")
    probe_log_tar_obj.addfile(
        util.default_tarinfo("README"),
        fileobj=io.BytesIO(b"This archive was generated by PROBE."),
    )
    probe_log_tar_obj.close()
    if debug:
        print()
        print("PROBE log files:")
        for path in probe_dir.glob("**/*"):
            if not path.is_dir():
                print(path, path.stat().st_size)
        print()
    shutil.rmtree(probe_dir)

@app.command()    
def transcribe_only(
        input_dir: pathlib.Path,
        output: pathlib.Path = pathlib.Path("probe_log"),
        debug: bool = typer.Option(default=False, help="Run in verbose mode"),
) -> None:
    """
    Transcribe the recorded data from INPUT_DIR into OUTPUT.
    """
    transcribe(input_dir, output, debug)

@app.command(
    context_settings=dict(
        ignore_unknown_options=True,
    ),
)
def record(
        cmd: list[str],
        gdb: bool = typer.Option(default=False, help="Run in GDB"),
        debug: bool = typer.Option(default=False, help="Run verbose & debug build of libprobe"),
        make: bool = typer.Option(default=False, help="Run make prior to executing"),
        output: pathlib.Path = pathlib.Path("probe_log"),
        no_transcribe: bool = typer.Option(default=False, help="Only execute without transcribing"),
) -> None:
    """
    Execute CMD... and optionally record its provenance into OUTPUT.
    """
    if make:
        proc = subprocess.run(
            ["make", "--directory", str(project_root / "libprobe"), "all"],
        )
        if proc.returncode != 0:
            typer.secho("Make failed", fg=typer.colors.RED)
            raise typer.Abort()
    if output.exists():
        output.unlink()
    libprobe = project_root / "libprobe/build" / ("libprobe-dbg.so" if debug or gdb else "libprobe.so")
    if not libprobe.exists():
        typer.secho(f"Libprobe not found at {libprobe}", fg=typer.colors.RED)
        raise typer.Abort()
    ld_preload = str(libprobe) + (":" + os.environ["LD_PRELOAD"] if "LD_PRELOAD" in os.environ else "")
    probe_dir = pathlib.Path(tempfile.mkdtemp(prefix=f"probe_log_{os.getpid()}"))
    if gdb:
        subprocess.run(
            ["gdb", "--args", "env", f"__PROBE_DIR={probe_dir}", f"LD_PRELOAD={ld_preload}", *cmd],
        )
    else:
        if debug:
            typer.secho(f"Running {cmd} with libprobe into {probe_dir}", fg=typer.colors.GREEN)
        proc = subprocess.run(
            cmd,
            env={**os.environ, "LD_PRELOAD": ld_preload, "__PROBE_DIR": str(probe_dir)},
        )

        if no_transcribe:
            typer.secho(f"Temporary probe directory: {probe_dir}", fg=typer.colors.YELLOW)
            raise typer.Exit(proc.returncode)
        
        transcribe(probe_dir, output, debug)
        raise typer.Exit(proc.returncode)

@app.command()
def process_graph(
        input: pathlib.Path = pathlib.Path("probe_log"),
) -> None:
    """
    Write a process graph from PROBE_LOG in DOT/graphviz format.
    """
    if not input.exists():
        typer.secho(f"INPUT {input} does not exist\nUse `PROBE record --output {input} CMD...` to rectify", fg=typer.colors.RED)
        raise typer.Abort()
    prov_log = parse_probe_log(input)
    console = rich.console.Console(file=sys.stderr)
    process_graph = analysis.provlog_to_digraph(prov_log)
    for warning in analysis.validate_provlog(prov_log):
        console.print(warning, style="red")
    rich.traceback.install(show_locals=False) # Figure out why we need this
    process_graph = analysis.provlog_to_digraph(prov_log)
    for warning in analysis.validate_hb_graph(prov_log, process_graph):
        console.print(warning, style="red")
    print(analysis.digraph_to_pydot_string(prov_log, process_graph))
    
@app.command()
def dataflow_graph(
        input: pathlib.Path = pathlib.Path("probe_log"),
) -> None:
    """
    Write a process graph from PROBE_LOG in DOT/graphviz format.
    """
    if not input.exists():
        typer.secho(f"INPUT {input} does not exist\nUse `PROBE record --output {input} CMD...` to rectify", fg=typer.colors.RED)
        raise typer.Abort()
    probe_log_tar_obj = tarfile.open(input, "r")
    prov_log = parse_probe_log(input)
    probe_log_tar_obj.close()
    console = rich.console.Console(file=sys.stderr)
    process_graph = analysis.provlog_to_digraph(prov_log)
    for warning in analysis.validate_provlog(prov_log):
        console.print(warning, style="red")
    rich.traceback.install(show_locals=False) # Figure out why we need this
    process_graph = analysis.provlog_to_digraph(prov_log)
    for warning in analysis.validate_hb_graph(prov_log, process_graph):
        console.print(warning, style="red")
    print(analysis.provlog_to_dataflow_graph(prov_log))


@app.command()
def dump(
        input: pathlib.Path = pathlib.Path("probe_log"),
) -> None:
    """
    Write the data from PROBE_LOG in a human-readable manner.
    """
    if not input.exists():
        typer.secho(f"INPUT {input} does not exist\nUse `PROBE record --output {input} CMD...` to rectify", fg=typer.colors.RED)
        raise typer.Abort()
    processes_prov_log = parse_probe_log(input)
    for pid, process in processes_prov_log.processes.items():
        print(pid)
        for exid, exec_epoch in process.exec_epochs.items():
            print(pid, exid)
            for tid, thread in exec_epoch.threads.items():
                print(pid, exid, tid)
                for op_no, op in enumerate(thread.ops):
                    print(pid, exid, tid, op_no, op.data)
                print()

@app.command(
    context_settings=dict(
        ignore_unknown_options=True,
    ),
)
def ssh(
        ssh_args: list[str],
        debug: bool = typer.Option(default=False, help="Run verbose & debug build of libprobe"),
):
    """
    Wrap SSH and record provenance of the remote command.
    """
    libprobe = project_root / "libprobe/build" / ("libprobe-dbg.so" if debug else "libprobe.so")
    if not libprobe.exists():
        typer.secho(f"Libprobe not found at {libprobe}", fg=typer.colors.RED)
        raise typer.Abort()

    # Create a temporary directory on the local machine
    local_temp_dir = pathlib.Path(tempfile.mkdtemp(prefix=f"probe_log_{os.getpid()}"))

    # Check if remote platform matches local platform
    remote_gcc_machine_cmd = ["ssh"] + ssh_args + ["gcc", "-dumpmachine"]
    local_gcc_machine_cmd = ["gcc", "-dumpmachine"]
    
    remote_gcc_machine = subprocess.check_output(remote_gcc_machine_cmd).decode().strip()
    local_gcc_machine = subprocess.check_output(local_gcc_machine_cmd).decode().strip()
    
    if remote_gcc_machine != local_gcc_machine:
        raise NotImplementedError("Remote platform is different from local platform")

    # Upload libprobe.so to the remote temporary directory
    remote_temp_dir_cmd = ["ssh"] + ssh_args + ["mktemp", "-d", "/tmp/probe_log_XXXXXX"]
    remote_temp_dir = subprocess.check_output(remote_temp_dir_cmd).decode().strip()
    remote_probe_dir = f"{remote_temp_dir}/probe_dir"
    
    scp_cmd = ["scp", str(libprobe), f"{ssh_args[0]}:{remote_temp_dir}/"]
    subprocess.run(scp_cmd, check=True)
    
    # Prepare the remote command with LD_PRELOAD and __PROBE_DIR
    ld_preload = f"{remote_temp_dir}/{libprobe.name}"
    remote_cmd = f"env LD_PRELOAD={ld_preload} __PROBE_DIR={remote_probe_dir} {' '.join(ssh_args[1:])}"
    
    if debug:
        typer.secho(f"Running remote command: {remote_cmd}", fg=typer.colors.GREEN)

    # Run the remote command
    ssh_cmd = ["ssh"] + ssh_args + [remote_cmd]
    proc = subprocess.run(ssh_cmd)

    # Download the provenance log from the remote machine
    remote_tar_cmd = ["ssh"] + ssh_args + [f"tar -czf - -C {remote_temp_dir} probe_dir"]
    with open(local_temp_dir / "probe_log.tar.gz", "wb") as f:
        subprocess.run(remote_tar_cmd, stdout=f, check=True)
    
    # Clean up the remote temporary directory
    remote_cleanup_cmd = ["ssh"] + ssh_args + [f"rm -rf {remote_temp_dir}"]
    subprocess.run(remote_cleanup_cmd, check=True)
    
    # Clean up the local temporary directory
    shutil.rmtree(local_temp_dir)
    
    raise typer.Exit(proc.returncode)

if __name__ == "__main__":
    app()

