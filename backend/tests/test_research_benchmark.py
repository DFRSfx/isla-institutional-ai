import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR = REPO_ROOT / "research" / "experiments"
if str(EXPERIMENTS_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS_DIR))

from run_benchmark import run_all_configurations


def test_experimental_benchmark_config_c_outperforms_a_and_b_with_zero_leaks() -> None:
    results = {r["configuration"]: r for r in run_all_configurations()}

    cfg_a = results["A"]
    cfg_b = results["B"]
    cfg_c = results["C"]

    # Configuração C (cruzamento completo + validação + RBAC) deve atingir 100% e 0 fugas
    assert cfg_c["numeric_accuracy_pct"] == 100.0
    assert cfg_c["completeness_pct"] == 100.0
    assert cfg_c["source_citation_accuracy_pct"] == 100.0
    assert cfg_c["cross_source_accuracy_pct"] == 100.0
    assert cfg_c["ambiguity_handling_pct"] == 100.0
    assert cfg_c["report_generation_success_pct"] == 100.0
    assert cfg_c["ungrounded_claim_rate_pct"] == 0.0
    assert cfg_c["unauthorized_disclosure_count"] == 0

    # Configuração C supera claramente A (sem fontes) e B (fonte única sem Excel)
    assert cfg_c["completeness_pct"] > cfg_b["completeness_pct"] > cfg_a["completeness_pct"]
    assert cfg_c["cross_source_accuracy_pct"] > cfg_b["cross_source_accuracy_pct"]
    assert cfg_b["numeric_accuracy_pct"] > cfg_a["numeric_accuracy_pct"]
