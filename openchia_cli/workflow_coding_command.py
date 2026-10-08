"""Interactive Target Workflow coding with input independent of the worker."""

import asyncio
import json
from queue import Empty, SimpleQueue

from agent.workflow_coding import WorkflowCodingConversation


HELP = """Target Workflow coding
Messages are saved immediately and handled in order. Sending keeps the current
turn running. /stop interrupts that turn and retains edits and queued messages.
/continue handles the remaining queue; an interrupted message is not repeated.
/status shows message delivery; /diff shows the coherent draft after a turn.
/handoff submits architecture, materialization and source for human review.
/back saves the conversation and returns to Duet; /code resume reopens it.
The Target Workflow is paused while this coding conversation owns editing.
"""


def open_from_cli(cli, text):
    parts = text.strip().split()
    if parts not in (["/code"], ["/code", "resume"]):
        cli._print_openchia("Usage: /code [resume]")
        return True
    if not cli._init_agent():
        return True
    from prompt_toolkit import PromptSession, print_formatted_text
    from prompt_toolkit.application import create_app_session, get_app
    from prompt_toolkit.application import run_in_terminal

    host = cli._episode_host()
    parent_app = get_app()
    conversation = None
    output = SimpleQueue()

    def print_pending():
        while True:
            try:
                text = output.get_nowait()
            except Empty:
                return
            print_formatted_text(text, output=parent_app.output)

    try:
        # Render worker output on this prompt's event loop. A global stdout
        # proxy can schedule against the suspended parent app in another loop.
        with create_app_session(input=parent_app.input, output=parent_app.output):
            output.put(HELP)
            conversation = WorkflowCodingConversation(host, resume=len(parts) == 2, emit=output.put)
            session = PromptSession()

            async def display_updates():
                while True:
                    if not output.empty():
                        await run_in_terminal(print_pending)
                    await asyncio.sleep(0.1)

            def start_display():
                session.app.create_background_task(display_updates())

            def toolbar():
                status = conversation.status()
                return (f"Coding: {status['state']} · queued {status['queued']} · "
                        f"last activity {status['seconds_since_activity']}s ago · /help")

            def show_status():
                status = conversation.status()
                messages = status.pop("messages")
                output.put(json.dumps(status, indent=2, ensure_ascii=False))
                for index, message in enumerate(messages, 1):
                    output.put(f"{index}. {message['state']}: {message['text']}")

            handlers = {
                "/help": lambda: output.put(HELP),
                "/status": show_status,
                "/stop": conversation.stop,
                "/continue": conversation.resume,
                "/diff": lambda: output.put(conversation.diff() or "No draft changes."),
            }
            while True:
                try:
                    message = session.prompt("CODE > ", bottom_toolbar=toolbar, refresh_interval=1,
                                             pre_run=start_display)
                except KeyboardInterrupt:
                    conversation.stop()
                    output.put("Stop requested. Edits and queued messages are retained.")
                    continue
                except EOFError:
                    break
                if not message.strip():
                    continue
                command = message.strip()
                if command == "/back":
                    break
                try:
                    if command == "/handoff":
                        result = conversation.handoff()
                        output.put(json.dumps(result, indent=2, ensure_ascii=False))
                        output.put("Review with /episode and approve with /approve; /build adopts these edited files and starts refinement.")
                        break
                    handler = handlers.get(command)
                    if handler is not None:
                        handler()
                    elif command.startswith("/"):
                        output.put("Use /help for coding conversation controls.")
                    else:
                        conversation.send(message)
                        output.put("Message saved.")
                except (ValueError, RuntimeError, OSError) as exc:
                    output.put(f"Coding: {exc}")
    except Exception as exc:
        cli._print_openchia(f"Coding conversation unavailable: {exc}")
    finally:
        if conversation is not None:
            conversation.close()
        print_pending()
        cli._refresh_openchia()
    return True


def open_inline(cli, event, text):
    from agent.memory_provider import ctx_bound
    from prompt_toolkit.application import run_in_terminal

    event.app.current_buffer.reset(append_to_history=True)
    future = run_in_terminal(ctx_bound(lambda: open_from_cli(cli, text)), in_executor=True)
    event.app.invalidate()
    return future
