from pathlib import Path
from planpilot.agent.agent import PlanPilotAgent

def test_agent_mcp_server_params_env():
    agent = PlanPilotAgent()
    assert agent.server_params.env is not None
    assert "PYTHONPATH" in agent.server_params.env
    src_dir = str(Path(__file__).resolve().parent.parent / "src")
    assert src_dir in agent.server_params.env["PYTHONPATH"]
