"""Governance policy tests.

The CMDB must support configurable validation policies that enforce
constraints on CIs by type. Policies are rules like "servers must have
an 'owner' attribute" — defined at runtime, not hard-coded.

API surface:
- POST   /policies             Create a policy
- GET    /policies             List all policies
- DELETE /policies/{id}        Remove a policy

Policy rules format:
  {
    "required_attributes": ["owner", "env"],
    "allowed_values": {"env": ["prod", "staging", "dev"]}
  }

Invariants:
- Creating a policy does not affect existing CIs retroactively
- New CIs of the governed type must comply with the policy
- Removing a policy lifts the constraint for future creates
- Policies for one CI type do not affect other types
"""
from __future__ import annotations

import pytest
from harness.client import CMDBClient, CMDBError


class TestPolicyCRUD:
    def test_create_and_list_policy(self, client: CMDBClient):
        policy = client.create_policy(
            ci_type="server",
            rules={"required_attributes": ["owner"]},
        )
        try:
            policies = client.list_policies()
            assert policy.id in [p.id for p in policies]
            assert policy.ci_type == "server"
        finally:
            client.delete_policy(policy.id)

    def test_delete_policy(self, client: CMDBClient):
        policy = client.create_policy(
            ci_type="temp_type",
            rules={"required_attributes": ["x"]},
        )
        client.delete_policy(policy.id)
        policies = client.list_policies()
        assert policy.id not in [p.id for p in policies]


class TestPolicyEnforcement:
    def test_missing_required_attribute_rejected(self, client: CMDBClient):
        """CI creation must fail when a required attribute is missing."""
        policy = client.create_policy(
            ci_type="server",
            rules={"required_attributes": ["owner"]},
        )
        try:
            # No "owner" attribute → should be rejected
            with pytest.raises(CMDBError) as exc:
                client.create_ci(name="no-owner", type="server")
            assert exc.value.status_code in (400, 422)
        finally:
            client.delete_policy(policy.id)

    def test_required_attribute_present_accepted(self, client: CMDBClient):
        policy = client.create_policy(
            ci_type="server",
            rules={"required_attributes": ["owner"]},
        )
        try:
            ci = client.create_ci(
                name="has-owner", type="server", attributes={"owner": "teamA"}
            )
            assert ci.attributes["owner"] == "teamA"
            client.delete_ci(ci.id)
        finally:
            client.delete_policy(policy.id)

    def test_allowed_values_enforcement(self, client: CMDBClient):
        policy = client.create_policy(
            ci_type="server",
            rules={
                "required_attributes": ["env"],
                "allowed_values": {"env": ["prod", "staging", "dev"]},
            },
        )
        try:
            # Valid value
            ci = client.create_ci(
                name="valid-env", type="server", attributes={"env": "prod"}
            )
            client.delete_ci(ci.id)

            # Invalid value
            with pytest.raises(CMDBError) as exc:
                client.create_ci(
                    name="bad-env", type="server", attributes={"env": "banana"}
                )
            assert exc.value.status_code in (400, 422)
        finally:
            client.delete_policy(policy.id)


class TestPolicyIsolation:
    def test_policy_does_not_affect_other_types(self, client: CMDBClient):
        """A policy on 'server' must not block 'app' creation."""
        policy = client.create_policy(
            ci_type="server",
            rules={"required_attributes": ["owner"]},
        )
        try:
            ci = client.create_ci(name="app-no-owner", type="app")
            client.delete_ci(ci.id)
        finally:
            client.delete_policy(policy.id)

    def test_removing_policy_lifts_constraint(self, client: CMDBClient):
        policy = client.create_policy(
            ci_type="server",
            rules={"required_attributes": ["owner"]},
        )
        # Should fail
        with pytest.raises(CMDBError):
            client.create_ci(name="before-removal", type="server")

        # Remove the policy
        client.delete_policy(policy.id)

        # Should now succeed
        ci = client.create_ci(name="after-removal", type="server")
        client.delete_ci(ci.id)

    def test_existing_cis_not_retroactively_invalidated(self, client: CMDBClient):
        """Creating a policy must not delete or invalidate existing CIs."""
        ci = client.create_ci(name="pre-policy", type="server")
        try:
            policy = client.create_policy(
                ci_type="server",
                rules={"required_attributes": ["owner"]},
            )
            try:
                # Pre-existing CI must still be readable
                fetched = client.get_ci(ci.id)
                assert fetched.name == "pre-policy"
            finally:
                client.delete_policy(policy.id)
        finally:
            client.delete_ci(ci.id)
