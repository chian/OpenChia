"""Two ChiaPets sharing an idea on the Duet's terminal splash."""

from rich.text import Text


def chia_duet_art(width: int) -> Text:
    """Keep both speakers together, including in a narrow terminal."""
    if width < 64:
        rows = (
            ("#8fb9a8", "  'Let's grow!'  'Together!'"),
            ("#80c875", r"     \|/           \|/"),
            ("#d99b76", "    (o o)>       <(o o)"),
            ("#d99b76", r"    /___\         /___\ "),
            ("#8fb9a8", "    HUMAN  <---->  LLM"),
        )
    else:
        # Equal-width speaker columns keep bubbles, foliage, faces and labels
        # on the same center lines. Mirror the pet instead of spacing it twice.
        column_width = 29
        mirror = str.maketrans("/\\()<>[]", "\\/)(><][")
        bubbles = (
            ("#8fb9a8", ".-------------------------.", ".-------------------------."),
            ("#d7e6dc", "|" + "What shall we grow?".center(25) + "|",
             "|" + "A great idea. Together.".center(25) + "|"),
            ("#8fb9a8", "'------------.------------'", "'------------.------------'"),
            ("#8fb9a8", "\\", "/"),
        )
        pets = (
            ("#80c875", r"    \  |  /    "),
            ("#a4d879", r"  \\ \ | / //  "),
            ("#80c875", "   .vvvvvvv.   "),
            ("#a4d879", r"  /vvvvvvvvv\  "),
            ("#d99b76", r" /  o     o  \ "),
            ("#e7af87", "(      ^      >"),
            ("#d99b76", r" \   \___/   / "),
            ("#d99b76", "  '._     _.'  "),
            ("#d99b76", r"  /_/     \_\  "),
        )
        pairs = (*bubbles, *((style, pet, pet[::-1].translate(mirror))
                             for style, pet in pets),
                 ("bold #8fb9a8", "HUMAN", "LLM"))
        rows = tuple(
            (style, "  " + left.center(column_width) + "    " + right.center(column_width))
            for style, left, right in pairs
        )
    art = Text(no_wrap=True, overflow="crop")
    for index, (style, line) in enumerate(rows):
        if index:
            art.append("\n")
        art.append(line, style=style)
    return art
