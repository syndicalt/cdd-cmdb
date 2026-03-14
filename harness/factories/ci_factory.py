"""Hypothesis strategies for generating valid CMDB inputs.

Import these in test modules rather than defining strategies inline,
so the data model evolves in one place.
"""
from hypothesis import strategies as st

# Printable text without control chars or surrogates
safe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    min_size=1,
    max_size=64,
)

ci_type_strategy = st.sampled_from([
    "server", "app", "network", "database", "storage", "container",
    "vm", "load_balancer", "firewall", "certificate", "service",
])

relationship_type_strategy = st.sampled_from([
    "hosts", "depends_on", "connects_to", "monitors", "backs_up",
    "load_balances", "contains", "replicates_to", "managed_by",
])

# Scalar attribute values only — nested objects are not valid
attribute_value_strategy = st.one_of(
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e9, max_value=1e9),
    safe_text,
    st.booleans(),
    st.none(),
)

ci_attributes_strategy = st.dictionaries(
    keys=safe_text,
    values=attribute_value_strategy,
    max_size=8,
)

ci_input_strategy = st.fixed_dictionaries({
    "name": safe_text,
    "type": ci_type_strategy,
    "attributes": ci_attributes_strategy,
})
