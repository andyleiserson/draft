from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

import loguru

from ..local_paths import Paths
from ..settings import get_settings
from .base import Query
from .command import FileOutputCommand, LoggerOutputCommand
from .step import CommandStep, LoggerOutputCommandStep, Status, Step


class GateType(StrEnum):
    COMPACT = "compact-gate"
    DESCRIPTIVE = "descriptive-gate"


@dataclass(kw_only=True)
class IPAQuery(Query):
    paths: Paths
    commit_hash: str

    def send_kill_signals(self):
        self.logger.info("sending kill signals")
        settings = get_settings()
        for helper in settings.other_helpers:
            response = helper.kill_query(self.query_id)
            self.logger.info(response)

    def crash(self):
        super().crash()
        self.send_kill_signals()


@dataclass(kw_only=True)
class IPACloneStep(LoggerOutputCommandStep):
    repo_path: Path
    repo_url: ClassVar[str] = "https://github.com/private-attribution/ipa.git"
    status: ClassVar[Status] = Status.STARTING

    @classmethod
    def build_from_query(cls, query: IPAQuery):
        return cls(
            repo_path=query.paths.repo_path,
            logger=query.logger,
        )

    def build_command(self) -> LoggerOutputCommand:
        return LoggerOutputCommand(
            cmd=f"git clone {self.repo_url} {self.repo_path}",
            logger=self.logger,
        )

    def pre_run(self):
        if self.repo_path.exists():
            self.skip = True


@dataclass(kw_only=True)
class IPAUpdateRemoteOriginStep(LoggerOutputCommandStep):
    repo_path: Path
    status: ClassVar[Status] = Status.STARTING

    @classmethod
    def build_from_query(cls, query: IPAQuery):
        return cls(
            repo_path=query.paths.repo_path,
            logger=query.logger,
        )

    def build_command(self) -> LoggerOutputCommand:
        return LoggerOutputCommand(
            cmd=f"git -C {self.repo_path} config --add remote.origin.fetch "
            "'+refs/pull/*/head:refs/remotes/origin/pr/*'",
            logger=self.logger,
        )


@dataclass(kw_only=True)
class IPAFetchUpstreamStep(LoggerOutputCommandStep):
    repo_path: Path
    status: ClassVar[Status] = Status.STARTING

    @classmethod
    def build_from_query(cls, query: IPAQuery):
        return cls(
            repo_path=query.paths.repo_path,
            logger=query.logger,
        )

    def build_command(self) -> LoggerOutputCommand:
        return LoggerOutputCommand(
            cmd=f"git -C {self.repo_path} fetch --all",
            logger=self.logger,
        )


@dataclass(kw_only=True)
class IPACheckoutCommitStep(LoggerOutputCommandStep):
    repo_path: Path
    commit_hash: str
    status: ClassVar[Status] = Status.STARTING

    @classmethod
    def build_from_query(cls, query: IPAQuery):
        return cls(
            repo_path=query.paths.repo_path,
            commit_hash=query.commit_hash,
            logger=query.logger,
        )

    def build_command(self) -> LoggerOutputCommand:
        return LoggerOutputCommand(
            cmd=f"git -C {self.repo_path} checkout -f {self.commit_hash}",
            logger=self.logger,
        )


@dataclass(kw_only=True)
class IPACorrdinatorCompileStep(LoggerOutputCommandStep):
    manifest_path: Path
    target_path: Path
    logger: loguru.Logger = field(repr=False)
    status: ClassVar[Status] = Status.COMPILING

    @classmethod
    def build_from_query(cls, query: IPAQuery):
        manifest_path = query.paths.repo_path / Path("Cargo.toml")
        return cls(
            manifest_path=manifest_path,
            target_path=query.paths.target_path,
            logger=query.logger,
        )

    def build_command(self) -> LoggerOutputCommand:
        return LoggerOutputCommand(
            cmd=f"cargo build --bin report_collector "
            f"--manifest-path={self.manifest_path} "
            f'--features="clap cli test-fixture" '
            f"--target-dir={self.target_path} --release",
            logger=self.logger,
        )


# pylint: disable=R0902
@dataclass(kw_only=True)
class IPAHelperCompileStep(LoggerOutputCommandStep):
    manifest_path: Path
    target_path: Path
    gate_type: GateType
    stall_detection: bool
    multi_threading: bool
    disable_metrics: bool
    reveal_aggregation: bool
    logger: loguru.Logger = field(repr=False)
    status: ClassVar[Status] = Status.COMPILING

    @classmethod
    def build_from_query(cls, query: IPAHelperQuery):
        manifest_path = query.paths.repo_path / Path("Cargo.toml")
        gate_type = query.gate_type
        stall_detection = query.stall_detection
        multi_threading = query.multi_threading
        disable_metrics = query.disable_metrics
        reveal_aggregation = query.reveal_aggregation
        return cls(
            manifest_path=manifest_path,
            target_path=query.paths.target_path,
            gate_type=gate_type,
            stall_detection=stall_detection,
            multi_threading=multi_threading,
            disable_metrics=disable_metrics,
            reveal_aggregation=reveal_aggregation,
            logger=query.logger,
        )

    def build_command(self) -> LoggerOutputCommand:
        return LoggerOutputCommand(
            cmd=f"cargo build --bin helper --manifest-path={self.manifest_path} "
            f'--features="web-app real-world-infra {self.gate_type}'
            f"{' stall-detection' if self.stall_detection else ''}"
            f"{' multi-threading' if self.multi_threading else ''}"
            f"{' reveal-aggregation' if self.reveal_aggregation else ''}"
            f"{' disable-metrics' if self.disable_metrics else ''}\" "
            f"--no-default-features --target-dir={self.target_path} "
            f"--release",
            logger=self.logger,
        )


@dataclass(kw_only=True)
class IPACoordinatorGenerateTestDataStep(CommandStep):
    output_file_path: Path
    report_collector_binary_path: Path
    size: int
    max_breakdown_key: int
    max_trigger_value: int
    status: ClassVar[Status] = Status.COMPILING

    def pre_run(self):
        self.output_file_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def build_from_query(cls, query: IPACoordinatorQuery):
        return cls(
            output_file_path=query.test_data_file,
            report_collector_binary_path=query.paths.report_collector_binary_path,
            size=query.size,
            max_breakdown_key=query.max_breakdown_key,
            max_trigger_value=query.max_trigger_value,
        )

    def build_command(self) -> FileOutputCommand:
        return FileOutputCommand(
            cmd=f"{self.report_collector_binary_path} gen-ipa-inputs -n {self.size} "
            f"--max-breakdown-key {self.max_breakdown_key} --report-filter all "
            f"--max-trigger-value {self.max_trigger_value} --seed 123",
            output_file_path=self.output_file_path,
        )


@dataclass(kw_only=True)
class IPACoordinatorWaitForHelpersStep(Step):
    query_id: str
    status: ClassVar[Status] = Status.WAITING_TO_START

    @classmethod
    def build_from_query(cls, query: IPAQuery):
        return cls(
            query_id=query.query_id,
        )

    def run(self):
        settings = get_settings()
        for helper in settings.other_helpers:
            max_unknonwn_status_wait_time = 100
            current_unknown_status_wait_time = 0
            loop_wait_time = 1
            while True:
                status = helper.get_current_query_status(self.query_id)
                match status:
                    case Status.IN_PROGRESS:
                        break
                    case Status.KILLED | Status.NOT_FOUND | Status.CRASHED:
                        self.success = False
                        return
                    case Status.STARTING | Status.COMPILING | Status.WAITING_TO_START:
                        # keep waiting while it's in a startup state
                        continue
                    case Status.UNKNOWN | Status.NOT_FOUND:
                        # eventually fail if the status is unknown or not found
                        # for ~100 seconds
                        current_unknown_status_wait_time += loop_wait_time
                        if (
                            current_unknown_status_wait_time
                            >= max_unknonwn_status_wait_time
                        ):
                            self.success = False
                            return

                time.sleep(1)
        time.sleep(3)  # allow enough time for the command to start

    def terminate(self):
        return

    def kill(self):
        return

    @property
    def cpu_usage_percent(self) -> float:
        return 0

    @property
    def memory_rss_usage(self) -> int:
        return 0


@dataclass(kw_only=True)
class IPACoordinatorStartStep(LoggerOutputCommandStep):
    network_config: Path
    report_collector_binary_path: Path
    test_data_path: Path
    max_breakdown_key: int
    max_trigger_value: int
    per_user_credit_cap: int
    malicious_security: bool
    status: ClassVar[Status] = Status.IN_PROGRESS

    @classmethod
    def build_from_query(cls, query: IPACoordinatorQuery):
        return cls(
            network_config=query.paths.config_path / Path("network.toml"),
            report_collector_binary_path=query.paths.report_collector_binary_path,
            test_data_path=query.test_data_file,
            max_breakdown_key=query.max_breakdown_key,
            max_trigger_value=query.max_trigger_value,
            per_user_credit_cap=query.per_user_credit_cap,
            malicious_security=query.malicious_security,
            logger=query.logger,
        )

    def build_command(self) -> LoggerOutputCommand:
        query_type = (
            "malicious-oprf-ipa-test"
            if self.malicious_security
            else "semi-honest-oprf-ipa-test"
        )
        return LoggerOutputCommand(
            cmd=f"{self.report_collector_binary_path} --network {self.network_config} "
            f"--input-file {self.test_data_path} {query_type} "
            f"--max-breakdown-key {self.max_breakdown_key} "
            f"--per-user-credit-cap {self.per_user_credit_cap} --plaintext-match-keys ",
            logger=self.logger,
        )


@dataclass(kw_only=True)
class IPACoordinatorQuery(IPAQuery):
    test_data_file: Path
    size: int
    max_breakdown_key: int
    max_trigger_value: int
    per_user_credit_cap: int
    malicious_security: bool

    step_classes: ClassVar[list[type[Step]]] = [
        IPACloneStep,
        IPAUpdateRemoteOriginStep,
        IPAFetchUpstreamStep,
        IPACheckoutCommitStep,
        IPACorrdinatorCompileStep,
        IPACoordinatorGenerateTestDataStep,
        IPACoordinatorWaitForHelpersStep,
        IPACoordinatorStartStep,
    ]

    def send_finish_signals(self):
        self.logger.info("sending finish signals")
        settings = get_settings()
        for helper in settings.other_helpers:
            resp = helper.finish_query(self.query_id)
            self.logger.info(resp)

    def finish(self):
        super().finish()
        self.send_finish_signals()


@dataclass(kw_only=True)
class IPAStartHelperStep(LoggerOutputCommandStep):
    # pylint: disable=too-many-instance-attributes
    helper_binary_path: Path
    identity: int
    network_path: Path
    tls_cert_path: Path
    tls_key_path: Path
    mk_public_path: Path
    mk_private_path: Path
    port: int
    status: ClassVar[Status] = Status.IN_PROGRESS

    @classmethod
    def build_from_query(cls, query: IPAHelperQuery):
        identity = query.role.value
        network_path = query.paths.config_path / Path("network.toml")
        tls_cert_path = query.paths.config_path / Path(f"pub/h{identity}.pem")
        tls_key_path = query.paths.config_path / Path(f"h{identity}.key")
        mk_public_path = query.paths.config_path / Path(f"pub/h{identity}_mk.pub")
        mk_private_path = query.paths.config_path / Path(f"h{identity}_mk.key")
        return cls(
            helper_binary_path=query.paths.helper_binary_path,
            identity=identity,
            network_path=network_path,
            tls_cert_path=tls_cert_path,
            tls_key_path=tls_key_path,
            mk_public_path=mk_public_path,
            mk_private_path=mk_private_path,
            port=query.port,
            logger=query.logger,
        )

    def build_command(self) -> LoggerOutputCommand:
        return LoggerOutputCommand(
            cmd=f"{self.helper_binary_path} --network {self.network_path} "
            f"--identity {self.identity} --tls-cert {self.tls_cert_path} "
            f"--tls-key {self.tls_key_path} --port {self.port} "
            f"--mk-public-key {self.mk_public_path} "
            f"--mk-private-key {self.mk_private_path}",
            logger=self.logger,
        )


@dataclass(kw_only=True)
class IPAHelperQuery(IPAQuery):
    port: int
    gate_type: GateType
    stall_detection: bool
    multi_threading: bool
    disable_metrics: bool
    reveal_aggregation: bool

    step_classes: ClassVar[list[type[Step]]] = [
        IPACloneStep,
        IPAUpdateRemoteOriginStep,
        IPAFetchUpstreamStep,
        IPACheckoutCommitStep,
        IPAHelperCompileStep,
        IPAStartHelperStep,
    ]
