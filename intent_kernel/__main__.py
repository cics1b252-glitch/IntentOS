"""Intent OS CLI — interactive terminal interface.

Run with: python -m intent_kernel
"""

from __future__ import annotations

import asyncio
import sys

from intent_kernel.application import ApplicationFactory
from intent_kernel.kernel import Kernel


BANNER = """
╔══════════════════════════════════════════════════╗
║         Intent OS v{version} — Kernel              ║
║  Cognitive Operating System                      ║
║  "Ampliar capacidade cognitiva, nunca substituir"║
╚══════════════════════════════════════════════════╝

Comandos:
  /status    — Status do Kernel
  /pkb       — Consultar PKB
  /export    — Exportar PKB
  /clear     — Limpar tela
  /quit      — Sair
""".format(version="0.1.0")


async def interactive_loop(kernel: Kernel) -> None:
    """Main interactive loop."""
    print(BANNER)

    while True:
        try:
            user_input = input("\n🔹 Sua intenção: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 Até logo!")
            break

        if not user_input:
            continue

        # Handle commands
        if user_input.startswith("/"):
            cmd = user_input.lower()
            if cmd == "/quit" or cmd == "/exit":
                print("\n👋 Até logo!")
                break
            elif cmd == "/status":
                _show_status(kernel)
            elif cmd == "/pkb":
                await _show_pkb(kernel)
            elif cmd == "/export":
                await _export_pkb(kernel)
            elif cmd == "/clear":
                print("\033[2J\033[H")
            else:
                print(f"❓ Comando desconhecido: {cmd}")
            continue

        # Process intent
        try:
            result = await kernel.process(user_input)
            _display_result(result)
        except Exception as e:
            print(f"\n❌ Erro: {e}")


def _show_status(kernel: Kernel) -> None:
    """Display kernel status."""
    status = kernel.status()
    print(f"\n📊 Status do Kernel:")
    print(f"  Versão: {status['version']}")
    print(f"  Constitution: v{status['constitution_version']}")
    print(f"  Providers: {', '.join(status['providers'])}")
    print(f"  Módulos: {', '.join(status['modules'])}")
    print(f"  PKB: {status['pkb_path']}")


async def _show_pkb(kernel: Kernel) -> None:
    """Display recent PKB events."""
    from intent_kernel.types import QueryFilters

    events = await kernel.query("")
    if not events:
        print("\n📝 PKB vazia — nenhum evento persistido ainda.")
        return

    print(f"\n📝 PKB — {len(events)} eventos:")
    for event in events[-10:]:  # last 10
        print(f"  [{event.lifecycle.value}] {event.type.value}: {event.title[:60]}")


async def _export_pkb(kernel: Kernel) -> None:
    """Export PKB to stdout."""
    data = await kernel.knowledge.export()
    print(f"\n📦 Exportação PKB ({len(data)} bytes):")
    print(data.decode()[:2000])
    if len(data) > 2000:
        print(f"\n... ({len(data) - 2000} bytes truncados)")


def _display_result(result) -> None:
    """Display a processing result."""
    print(f"\n{'='*50}")
    print(result.text)
    print(f"{'='*50}")

    if result.events:
        print(f"\n📝 Conhecimento persistido ({len(result.events)} eventos):")
        for event in result.events:
            print(f"  - [{event.type.value}] {event.title[:60]}")

    if result.next_steps:
        print(f"\n💡 Próximos passos:")
        for step in result.next_steps:
            print(f"  → {step}")


def create_cli_kernel(
    factory: ApplicationFactory | None = None,
) -> Kernel:
    """Obtain the CLI Kernel from the official Composition Root."""
    return (factory or ApplicationFactory()).get_kernel()


def main():
    """Entry point for the CLI."""
    kernel = create_cli_kernel()
    asyncio.run(interactive_loop(kernel))


if __name__ == "__main__":
    main()
