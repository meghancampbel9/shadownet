from pathlib import Path

PLUGIN_DIR = Path(__file__).parent


def register(ctx):
    ctx.register_skill(
        "shadownet-local",
        PLUGIN_DIR / "skills" / "shadownet-local" / "SKILL.md",
    )
    ctx.register_skill(
        "shadownet-local-coordination",
        PLUGIN_DIR / "skills" / "shadownet-local-coordination" / "SKILL.md",
    )
