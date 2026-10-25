"""Discord UI menu state and view builders for AstrBot's existing Pycord client.

The adapter owns the gateway and slash command.  This module never starts a
second client and imports Pycord only when a Discord menu is actually opened.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .telegram_menu_runtime import MODES


@dataclass
class Draft:
    mode: str
    created: float
    source_event: object
    draft_id: str = ""
    stage: str = "image"
    body: str = ""
    image_path: str = ""
    selected_job: tuple | None = None
    image_event: object | None = None
    claimed: bool = False

    def expired(self, now: float | None = None) -> bool:
        return (time.monotonic() if now is None else now) - self.created > 600


def draft_key(event) -> tuple[str, str]:
    return str(event.get_session_id()), str(event.get_sender_id())


def interaction_matches(interaction, key: tuple[str, str]) -> bool:
    return (str(getattr(interaction, "channel_id", "")) == key[0]
            and str(getattr(getattr(interaction, "user", None), "id", "")) == key[1])


def mode_view(plugin, key: tuple[str, str], menu_id: str):
    import discord

    class ModeSelect(discord.ui.Select):
        def __init__(self):
            super().__init__(
                placeholder="选择生图模式",
                min_values=1,
                max_values=1,
                options=[discord.SelectOption(label=label[:100], value=label)
                         for label in MODES],
            )

        async def callback(self, interaction):
            if not interaction_matches(interaction, key):
                await interaction.response.send_message("这不是你的菜单。", ephemeral=True)
                return
            await plugin._discord_menu_select(interaction, key, menu_id, self.values[0])

    view = discord.ui.View(timeout=600)
    view.add_item(ModeSelect())
    return view


def prompt_modal(plugin, key: tuple[str, str], mode: str, draft_id: str):
    import discord

    command, _, required = MODES[mode]

    class PromptModal(discord.ui.Modal):
        def __init__(self):
            super().__init__(title=mode[:45], timeout=600)
            self.prompt = discord.ui.InputText(
                label="提示词或补充参数",
                placeholder=("例如：自动 雨夜街道" if command == "amulti"
                             else "例如：角色=名称 画风=名称，或直接填写提示词"),
                style=discord.InputTextStyle.long,
                required=required,
                max_length=4000,
            )
            self.add_item(self.prompt)

        async def callback(self, interaction):
            if not interaction_matches(interaction, key):
                await interaction.response.send_message("这不是你的菜单。", ephemeral=True)
                return
            await plugin._discord_menu_text(interaction, key, draft_id, mode,
                                            str(self.prompt.value or "").strip())

    return PromptModal()


def confirm_view(plugin, key: tuple[str, str], draft_id: str):
    import discord

    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=600)

        @discord.ui.button(label="确认提交", style=discord.ButtonStyle.success)
        async def confirm(self, button, interaction):
            if not interaction_matches(interaction, key):
                await interaction.response.send_message("这不是你的菜单。", ephemeral=True)
                return
            await plugin._discord_menu_confirm(interaction, key, draft_id)

        @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
        async def cancel(self, button, interaction):
            if not interaction_matches(interaction, key):
                await interaction.response.send_message("这不是你的菜单。", ephemeral=True)
                return
            await plugin._discord_menu_cancel(interaction, key, draft_id)

    return ConfirmView()
