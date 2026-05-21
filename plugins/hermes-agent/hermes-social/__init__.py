from pathlib import Path

PLUGIN_DIR = Path(__file__).parent


def register(ctx):
    ctx.register_skill(
        "hermes-social",
        PLUGIN_DIR / "skills" / "hermes-social" / "SKILL.md",
    )
    ctx.register_skill(
        "hermes-social-coordination",
        PLUGIN_DIR / "skills" / "hermes-social-coordination" / "SKILL.md",
    )
