"""A short brief for each planned session: what it's for and how to do it.
Plain rules, no model: the chat can expand on it but never changes it."""
from __future__ import annotations

PURPOSE = {
    ("run", "easy"): "Aerobic base: builds the engine without adding fatigue.",
    ("run", "long"): "The week's key run: endurance and time on your feet. Practice fueling.",
    ("run", "strides"): "Easy aerobic run, plus a little leg speed that costs almost nothing.",
    ("run", "tempo"): "Threshold work: raises the pace you can hold for an hour.",
    ("run", "race_pace"): "Rehearse goal pace so race day feels familiar.",
    ("run", "brick"): "Run off the bike: teaches your legs the 70.3 transition.",
    ("run", "shakeout"): "Loosen up, nothing more.",
    ("swim", "easy"): "Technique and aerobic swim fitness. Smooth, not hard.",
    ("swim", "css"): "Swim threshold (CSS) set: the pace you can hold for the 70.3 swim.",
    ("bike", "easy"): "Aerobic bike base. The 70.3 is mostly won on the bike.",
    ("bike", "long"): "Long aerobic ride: bike endurance and fueling practice.",
    ("bike", "threshold"): "Bike threshold intervals: raises the power you can hold.",
    ("strength", "heavy"): "Strength that protects the running and keeps muscle.",
    ("strength", "light"): "Light strength: keep the habit, no straining.",
    ("strength", "bodyweight"): "Bodyweight strength you can do in a hotel room.",
}


def brief(sport: str, kind: str, *, zone: str = "Z2", distance_mi: float | None = None,
          duration_min: float | None = None, hr_cap: int | None = None, walk_over: int | None = None,
          returning: bool = False, provisional: bool = False, place_note: str = "") -> str:
    parts = [PURPOSE.get((sport, kind)) or PURPOSE.get((sport, "easy")) or "Planned session."]
    if sport == "run":
        if kind in ("easy", "long", "strides", "shakeout", "brick"):
            how = "Conversational the whole way"
            if hr_cap:
                how += f": average HR under {hr_cap}"
            if walk_over:
                how += f", walk if it passes {walk_over}"
            parts.append(how + ".")
        if kind == "strides":
            parts.append("Finish with 4-6 x 20 s relaxed strides, full recovery between.")
        if kind == "long" and (distance_mi or 0) >= 10:
            parts.append("Take a gel every 40-45 min and drink to thirst.")
    elif sport in ("swim", "bike") and zone in ("Z1", "Z2"):
        parts.append("Keep it easy: you should be able to talk in full sentences.")
    elif sport == "strength" and kind != "heavy":
        parts.append("Stop 2-3 reps short of failure. No breath-holding on heavy efforts.")
    if returning:
        parts.append("Coming back from mono: stop and tell the doctor if you get unusual fatigue, "
                     "a sore throat, fever, or pain under the left ribs.")
    if place_note:
        parts.append(place_note)
    if provisional:
        parts.append("Preview only: nothing starts until the doctor clears you.")
    return " ".join(parts)
