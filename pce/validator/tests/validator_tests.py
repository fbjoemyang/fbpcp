#!/usr/bin/env python3
# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

# pyre-strict

from typing import Optional, List
from unittest import TestCase
from unittest.mock import MagicMock

from fbpcp.entity.container_definition import ContainerDefinition
from fbpcp.entity.firewall_ruleset import FirewallRuleset, FirewallRule
from fbpcp.entity.route_table import (
    RouteTargetType,
    Route,
    RouteState,
)
from fbpcp.entity.subnet import Subnet
from fbpcp.entity.vpc_peering import VpcPeeringState
from pce.validator.pce_standard_constants import (
    AvailabilityZone,
    CONTAINER_CPU,
    CONTAINER_MEMORY,
    CONTAINER_IMAGE,
    FIREWALL_RULE_FINAL_PORT,
    FIREWALL_RULE_INITIAL_PORT,
)
from pce.validator.validation_suite import (
    ValidationResult,
    ValidationResultCode,
    ValidationErrorDescriptionTemplate,
    ValidationErrorSolutionHintTemplate,
    ValidationWarningDescriptionTemplate,
    ClusterResourceType,
    ValidationSuite,
)


def create_mock_firewall_rule(
    cidr: str,
    from_port: int = FIREWALL_RULE_INITIAL_PORT,
    to_port: int = FIREWALL_RULE_FINAL_PORT,
) -> FirewallRule:
    fr = MagicMock()
    fr.from_port = from_port
    fr.to_port = to_port
    fr.cidr = cidr
    return fr


def create_mock_firewall_rule_set(ingress: List[FirewallRule]) -> FirewallRuleset:
    frs = MagicMock()
    frs.vpc_id = "create_mock_firewall_rule_set"
    frs.ingress = ingress
    return frs


def create_mock_route(
    cidr: str, target_type: RouteTargetType, state: RouteState = RouteState.ACTIVE
) -> Route:
    r = MagicMock()
    r.destination_cidr_block = cidr
    r.state = state
    r.route_target = MagicMock()
    r.route_target.route_target_type = target_type
    r.route_target.route_target_id = f"target_{target_type.name}_{cidr}"
    return r


def create_mock_subnet(availability_zone: AvailabilityZone) -> Subnet:
    s = MagicMock()
    s.availability_zone = availability_zone
    return s


def create_mock_container_definition(
    cpu: int, memory: int, image: str
) -> ContainerDefinition:
    c = MagicMock()
    c.cpu = cpu
    c.memory = memory
    c.image = image
    return c


class TestValidator(TestCase):
    TEST_REGION = "us-east-1"
    TEST_AZS = [
        "us-east-1-bos-1a",
        "us-east-1-chi-1a",
        "us-east-1-dfw-1a",
    ]
    TEST_VPC_ID = "test_vpc_id"
    TEST_PCE_ID = "test_pce_id"

    def setUp(self) -> None:
        self.ec2_gateway = MagicMock()
        self.validator = ValidationSuite(
            "test_region", "test_key_id", "test_key_data", ec2_gateway=self.ec2_gateway
        )
        self.maxDiff = None

    def _test_validate_private_cidr(
        self,
        cidr: str,
        expected_result: Optional[ValidationResult],
        expected_error_msg: Optional[str] = None,
    ) -> None:
        pce = MagicMock()
        pce.pce_network = MagicMock()
        pce.pce_network.vpc = MagicMock()
        pce.pce_network.vpc.vpc_id = TestValidator.TEST_VPC_ID
        pce.pce_network.region = "us-east-1"
        pce.pce_network.vpc.cidr = cidr

        if expected_error_msg:
            with self.assertRaises(Exception) as ex:
                self.validator.validate_private_cidr(pce)
            self.assertEquals(expected_error_msg, str(ex.exception))
            return

        actual_result = self.validator.validate_private_cidr(pce)
        self.assertEquals(expected_result, actual_result)

    def test_validate_private_cidr_non_valid(self) -> None:
        for invalid_ip in ["non_valid", "10.1.1.300"]:
            self._test_validate_private_cidr(
                invalid_ip,
                None,
                f"'{invalid_ip}' does not appear to be an IPv4 or IPv6 network",
            )

    def test_validate_private_cidr_success(self) -> None:
        for invalid_ip in ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]:
            self._test_validate_private_cidr(
                invalid_ip, ValidationResult(ValidationResultCode.SUCCESS)
            )

    def test_validate_private_cidr_fail(self) -> None:
        for invalid_ip in ["10.0.0.0/7", "173.16.0.0/12", "192.168.0.0/15"]:
            self._test_validate_private_cidr(
                invalid_ip,
                ValidationResult(
                    ValidationResultCode.ERROR,
                    ValidationErrorDescriptionTemplate.NON_PRIVATE_VPC_CIDR.value.format(
                        vpc_cidr=TestValidator.TEST_VPC_ID
                    ),
                    ValidationErrorSolutionHintTemplate.NON_PRIVATE_VPC_CIDR.value,
                ),
                None,
            )

    def _test_validate_firewall(
        self,
        vpc_cidr: str,
        routes: List[Route],
        firewall_rulesets: List[FirewallRuleset],
        expected_result: ValidationResult,
        expected_error_msg: Optional[str] = None,
    ) -> None:
        pce = MagicMock()
        pce.pce_network = MagicMock()
        pce.pce_network.vpc = MagicMock()
        pce.pce_network.vpc.vpc_id = TestValidator.TEST_VPC_ID
        pce.pce_network.vpc.cidr = vpc_cidr
        pce.pce_network.vpc.tags = {"pce:pce-id": TestValidator.TEST_PCE_ID}
        pce.pce_network.firewall_rulesets = firewall_rulesets
        pce.pce_network.route_table = MagicMock()
        pce.pce_network.route_table.routes = routes

        if expected_error_msg:
            with self.assertRaises(Exception) as ex:
                self.validator.validate_firewall(pce)
            self.assertEquals(expected_error_msg, str(ex.exception))
            return

        actual_result = self.validator.validate_firewall(pce)
        self.assertEquals(expected_result, actual_result)

    def test_validate_firewall_not_overlapping_vpc(self) -> None:
        """
        No firewall rules allows inbound traffic from the peer
        """
        self._test_validate_firewall(
            "10.1.0.0/16",
            [
                create_mock_route("11.2.0.0/16", RouteTargetType.VPC_PEERING),
            ],
            [
                create_mock_firewall_rule_set(
                    [
                        create_mock_firewall_rule("10.2.0.0/16"),
                        create_mock_firewall_rule("10.1.1.0/24"),
                        create_mock_firewall_rule("10.3.0.0/16"),
                    ]
                )
            ],
            ValidationResult(
                ValidationResultCode.ERROR,
                ValidationErrorDescriptionTemplate.FIREWALL_INVALID_RULESETS.value.format(
                    error_reasons=str(
                        ValidationErrorDescriptionTemplate.FIREWALL_CIDR_NOT_OVERLAPS_VPC.value.format(
                            peer_target_id="target_VPC_PEERING_11.2.0.0/16",
                            vpc_id=TestValidator.TEST_VPC_ID,
                            vpc_cidr="10.1.0.0/16",
                        )
                    )
                ),
                ValidationErrorSolutionHintTemplate.FIREWALL_INVALID_RULESETS.value,
            ),
        )

    def test_validate_firewall_bad_port_range(self) -> None:
        initial_port = FIREWALL_RULE_INITIAL_PORT + 1
        self._test_validate_firewall(
            "10.1.0.0/16",
            [
                create_mock_route("12.4.1.0/24", RouteTargetType.VPC_PEERING),
            ],
            [
                create_mock_firewall_rule_set(
                    [
                        create_mock_firewall_rule("10.2.0.0/16"),
                        create_mock_firewall_rule("12.4.0.0/16", initial_port),
                        create_mock_firewall_rule("10.3.0.0/16"),
                    ]
                )
            ],
            ValidationResult(
                ValidationResultCode.ERROR,
                ValidationErrorDescriptionTemplate.FIREWALL_INVALID_RULESETS.value.format(
                    error_reasons=str(
                        ValidationErrorDescriptionTemplate.FIREWALL_CIDR_CANT_CONTAIN_EXPECTED_RANGE.value.format(
                            fr_vpc_id="create_mock_firewall_rule_set",
                            fri_cidr="12.4.0.0/16",
                            fri_from_port=initial_port,
                            fri_to_port=FIREWALL_RULE_FINAL_PORT,
                        )
                    )
                ),
                ValidationErrorSolutionHintTemplate.FIREWALL_INVALID_RULESETS.value,
            ),
        )

    def test_validate_firewall_success(self) -> None:
        self._test_validate_firewall(
            "10.1.0.0/16",
            [
                create_mock_route("12.4.1.0/24", RouteTargetType.VPC_PEERING),
            ],
            [
                create_mock_firewall_rule_set(
                    [
                        create_mock_firewall_rule("10.2.0.0/16"),
                        create_mock_firewall_rule("12.4.0.0/16"),
                        create_mock_firewall_rule("10.3.0.0/16"),
                    ]
                )
            ],
            ValidationResult(ValidationResultCode.SUCCESS),
        )

    def test_validate_firewall_exceeding_port_range(self) -> None:
        initial_port = FIREWALL_RULE_INITIAL_PORT - 1
        self._test_validate_firewall(
            "10.1.0.0/16",
            [
                create_mock_route("12.4.1.0/24", RouteTargetType.VPC_PEERING),
            ],
            [
                create_mock_firewall_rule_set(
                    [
                        create_mock_firewall_rule("10.2.0.0/16"),
                        create_mock_firewall_rule("12.4.0.0/16", initial_port),
                        create_mock_firewall_rule("10.3.0.0/16"),
                    ]
                )
            ],
            ValidationResult(
                ValidationResultCode.WARNING,
                ValidationWarningDescriptionTemplate.FIREWALL_FLAGGED_RULESETS.value.format(
                    warning_reasons=str(
                        ValidationWarningDescriptionTemplate.FIREWALL_CIDR_EXCEED_EXPECTED_RANGE.value.format(
                            fr_vpc_id="create_mock_firewall_rule_set",
                            fri_cidr="12.4.0.0/16",
                            fri_from_port=initial_port,
                            fri_to_port=FIREWALL_RULE_FINAL_PORT,
                        )
                    )
                ),
            ),
        )

    def test_validate_firewall_no_rulez(self) -> None:
        self._test_validate_firewall(
            "10.1.0.0/16",
            [
                create_mock_route("12.4.1.0/24", RouteTargetType.VPC_PEERING),
            ],
            [],
            ValidationResult(
                ValidationResultCode.ERROR,
                ValidationErrorDescriptionTemplate.FIREWALL_RULES_NOT_FOUND.value.format(
                    pce_id=TestValidator.TEST_PCE_ID
                ),
            ),
        )

    def _test_validate_route_table(
        self,
        routes: List[Route],
        expected_result: ValidationResult,
        expected_error_msg: Optional[str] = None,
    ) -> None:
        pce = MagicMock()
        pce.pce_network = MagicMock()
        pce.pce_network.vpc = MagicMock()
        pce.pce_network.route_table = MagicMock()
        pce.pce_network.route_table.routes = routes

        if expected_error_msg:
            with self.assertRaises(Exception) as ex:
                self.validator.validate_route_table(pce)
            self.assertEquals(expected_error_msg, str(ex.exception))
            return

        actual_result = self.validator.validate_route_table(pce)
        self.assertEquals(expected_result, actual_result)

    def test_validate_route_table_no_vpc_peering(self) -> None:
        self._test_validate_route_table(
            [
                create_mock_route("11.2.0.0/16", RouteTargetType.INTERNET),
                create_mock_route("11.3.0.0/16", RouteTargetType.OTHER),
                create_mock_route("11.4.0.0/16", RouteTargetType.INTERNET),
            ],
            ValidationResult(
                validation_result_code=ValidationResultCode.ERROR,
                description=ValidationErrorDescriptionTemplate.ROUTE_TABLE_VPC_PEERING_MISSING.value,
                solution_hint=ValidationErrorSolutionHintTemplate.ROUTE_TABLE_VPC_PEERING_MISSING.value,
            ),
        )

    def test_validate_route_table_route_not_active(self) -> None:
        self._test_validate_route_table(
            [
                create_mock_route("11.2.0.0/16", RouteTargetType.INTERNET),
                create_mock_route(
                    "10.3.0.0/16", RouteTargetType.VPC_PEERING, RouteState.UNKNOWN
                ),
                create_mock_route("11.4.0.0/16", RouteTargetType.INTERNET),
            ],
            ValidationResult(
                validation_result_code=ValidationResultCode.ERROR,
                description=ValidationErrorDescriptionTemplate.ROUTE_TABLE_VPC_PEERING_MISSING.value,
                solution_hint=ValidationErrorSolutionHintTemplate.ROUTE_TABLE_VPC_PEERING_MISSING.value,
            ),
        )

    def test_validate_route_table_success(self) -> None:
        self._test_validate_route_table(
            [
                create_mock_route("11.2.0.0/16", RouteTargetType.INTERNET),
                create_mock_route("10.1.0.0/16", RouteTargetType.VPC_PEERING),
                create_mock_route("11.4.0.0/16", RouteTargetType.INTERNET),
            ],
            ValidationResult(ValidationResultCode.SUCCESS),
        )

    def _test_validate_subnet(
        self,
        subnet_availability_zones: List[AvailabilityZone],
        region_availability_zones: List[AvailabilityZone],
        expected_result: ValidationResult,
        expected_error_msg: Optional[str] = None,
    ) -> None:
        pce = MagicMock()
        pce.pce_network = MagicMock()
        pce.pce_network.region = "us-east-1"
        pce.pce_network.subnets = [
            create_mock_subnet(az) for az in subnet_availability_zones
        ]
        self.ec2_gateway.describe_availability_zones = MagicMock(
            return_value=region_availability_zones
        )

        if expected_error_msg:
            with self.assertRaises(Exception) as ex:
                self.validator.validate_subnets(pce)
            self.assertEquals(expected_error_msg, str(ex.exception))
            return

        actual_result = self.validator.validate_subnets(pce)
        self.assertEquals(expected_result, actual_result)

    def test_validate_subnet_single_zone(self) -> None:
        self._test_validate_subnet(
            [
                "us-east-1-bos-1a",
                "us-east-1-bos-1a",
                "us-east-1-bos-1a",
            ],
            TestValidator.TEST_AZS,
            ValidationResult(
                ValidationResultCode.ERROR,
                ValidationErrorDescriptionTemplate.NOT_ALL_AZ_USED.value,
                ValidationErrorSolutionHintTemplate.NOT_ALL_AZ_USED.value.format(
                    region=TestValidator.TEST_REGION,
                    azs=",".join(TestValidator.TEST_AZS),
                ),
            ),
        )

    def test_validate_subnet_more_subnets_than_zone(self) -> None:
        self._test_validate_subnet(
            [
                "us-east-1-bos-1a",
                "us-east-1-chi-1a",
                "us-east-1-chi-1a",
            ],
            TestValidator.TEST_AZS,
            ValidationResult(
                ValidationResultCode.ERROR,
                ValidationErrorDescriptionTemplate.NOT_ALL_AZ_USED.value,
                ValidationErrorSolutionHintTemplate.NOT_ALL_AZ_USED.value.format(
                    region=TestValidator.TEST_REGION,
                    azs=",".join(TestValidator.TEST_AZS),
                ),
            ),
        )

    def test_validate_subnet_success(self) -> None:
        self._test_validate_subnet(
            TestValidator.TEST_AZS,
            TestValidator.TEST_AZS,
            ValidationResult(ValidationResultCode.SUCCESS),
        )

    def _test_validate_cluster_definition(
        self,
        cpu: int,
        memory: int,
        image: str,
        expected_result: ValidationResult,
        expected_error_msg: Optional[str] = None,
    ) -> None:
        pce = MagicMock()
        pce.pce_compute = MagicMock()
        pce.pce_compute.container_definition = create_mock_container_definition(
            cpu, memory, image
        )

        if expected_error_msg:
            with self.assertRaises(Exception) as ex:
                self.validator.validate_cluster_definition(pce)
            self.assertEquals(expected_error_msg, str(ex.exception))
            return

        actual_result = self.validator.validate_cluster_definition(pce)
        self.assertEquals(expected_result, actual_result)

    def test_validate_cluster_definition_wrong_cpu(self) -> None:
        cpu = CONTAINER_CPU * 2
        self._test_validate_cluster_definition(
            cpu,
            CONTAINER_MEMORY,
            CONTAINER_IMAGE,
            ValidationResult(
                ValidationResultCode.ERROR,
                ValidationErrorDescriptionTemplate.CLUSTER_DEFINITION_WRONG_VALUES.value.format(
                    error_reasons=",".join(
                        [
                            ValidationErrorDescriptionTemplate.CLUSTER_DEFINITION_WRONG_VALUE.value.format(
                                resource_name=ClusterResourceType.CPU.name.title(),
                                value=cpu,
                                expected_value=CONTAINER_CPU,
                            )
                        ]
                    )
                ),
                ValidationErrorSolutionHintTemplate.CLUSTER_DEFINITION_WRONG_VALUES.value,
            ),
        )

    def test_validate_cluster_definition_success(self) -> None:
        self._test_validate_cluster_definition(
            CONTAINER_CPU,
            CONTAINER_MEMORY,
            CONTAINER_IMAGE,
            ValidationResult(ValidationResultCode.SUCCESS),
        )

    def test_validate_cluster_definition_wrong_image(self) -> None:
        image = "foo_image"
        self._test_validate_cluster_definition(
            CONTAINER_CPU,
            CONTAINER_MEMORY,
            image,
            ValidationResult(
                ValidationResultCode.WARNING,
                ValidationWarningDescriptionTemplate.CLUSTER_DEFINITION_FLAGGED_VALUES.value.format(
                    warning_reasons=",".join(
                        [
                            ValidationWarningDescriptionTemplate.CLUSTER_DEFINITION_FLAGGED_VALUE.value.format(
                                resource_name=ClusterResourceType.IMAGE.name.title(),
                                value=image,
                                expected_value=CONTAINER_IMAGE,
                            )
                        ]
                    )
                ),
            ),
        )

    def _test_validate_network_and_compute(
        self,
        vpc_cidr: str,
        routes: List[Route],
        firewall_rulesets: List[FirewallRuleset],
        cpu: int,
        expected_result: List[ValidationResult],
        expected_error_msg: Optional[str] = None,
    ) -> None:
        pce = MagicMock()
        pce.pce_network = MagicMock()
        pce.pce_network.vpc = MagicMock()
        pce.pce_network.vpc.vpc_id = TestValidator.TEST_VPC_ID
        pce.pce_network.vpc.cidr = vpc_cidr
        pce.pce_network.firewall_rulesets = firewall_rulesets
        pce.pce_network.route_table = MagicMock()
        pce.pce_network.route_table.routes = routes
        pce.pce_network.subnets = []
        pce.pce_network.vpc_peering = MagicMock()
        pce.pce_network.vpc_peering.status = VpcPeeringState.ACTIVE
        pce.pce_compute = MagicMock()
        pce.pce_compute.container_definition = create_mock_container_definition(
            cpu, CONTAINER_MEMORY, CONTAINER_IMAGE
        )

        self.ec2_gateway.describe_availability_zones = MagicMock(return_value=[])

        if expected_error_msg:
            with self.assertRaises(Exception) as ex:
                self.validator.validate_network_and_compute(pce)
            self.assertEquals(expected_error_msg, str(ex.exception))
            return

        actual_result = self.validator.validate_network_and_compute(pce)
        self.assertEquals(expected_result, actual_result)

    def test_validate_network_and_compute_not_overlapping_firewall_cidr_and_wrong_cpu(
        self,
    ) -> None:
        cpu = CONTAINER_CPU + 1
        self._test_validate_network_and_compute(
            "10.1.0.0/16",
            [
                create_mock_route("12.4.1.0/24", RouteTargetType.VPC_PEERING),
            ],
            [
                create_mock_firewall_rule_set(
                    [
                        create_mock_firewall_rule("10.2.0.0/16"),
                        create_mock_firewall_rule("10.1.1.0/24"),
                        create_mock_firewall_rule("10.3.0.0/16"),
                    ]
                )
            ],
            cpu,
            [
                ValidationResult(
                    ValidationResultCode.ERROR,
                    ValidationErrorDescriptionTemplate.FIREWALL_INVALID_RULESETS.value.format(
                        error_reasons=str(
                            ValidationErrorDescriptionTemplate.FIREWALL_CIDR_NOT_OVERLAPS_VPC.value.format(
                                peer_target_id="target_VPC_PEERING_12.4.1.0/24",
                                vpc_id=TestValidator.TEST_VPC_ID,
                                vpc_cidr="10.1.0.0/16",
                            )
                        )
                    ),
                    ValidationErrorSolutionHintTemplate.FIREWALL_INVALID_RULESETS.value,
                ),
                ValidationResult(
                    ValidationResultCode.ERROR,
                    ValidationErrorDescriptionTemplate.CLUSTER_DEFINITION_WRONG_VALUES.value.format(
                        error_reasons=",".join(
                            [
                                ValidationErrorDescriptionTemplate.CLUSTER_DEFINITION_WRONG_VALUE.value.format(
                                    resource_name=ClusterResourceType.CPU.name.title(),
                                    value=cpu,
                                    expected_value=CONTAINER_CPU,
                                )
                            ]
                        )
                    ),
                    ValidationErrorSolutionHintTemplate.CLUSTER_DEFINITION_WRONG_VALUES.value,
                ),
            ],
        )
