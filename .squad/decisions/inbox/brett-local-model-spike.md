# Local CPU model spike (issue #3), Brett, 2026-10-09

- Measured (compatibility.md B11): Qwen2.5-3B Q4 passed 22/22 on our two-tool eval; Qwen2.5-1.5B 20/22 (invented tool); Llama-3.2-3B 13/22 (calls tools when told not to).
- Threshold: >=90% both-tool, 0 invented, 0 bad args, no spurious calls.
- Recommendation: continue evaluating Qwen2.5-3B only; latency (about 1 min/prompt on a laptop, cause undiagnosed) is the open risk. Not a Foundry replacement yet.
- Script is a SPIKE (`scripts/spike_local_model_eval.py`); models and venv deleted.
