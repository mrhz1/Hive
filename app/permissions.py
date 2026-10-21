PERMISSION_MODELS = ("user", "patient", "role", "application")
PERMISSION_ACTIONS = ("view", "create", "update", "delete")

MODEL_ACTIONS = {model: PERMISSION_ACTIONS for model in PERMISSION_MODELS}
MODEL_ACTIONS["log"] = ("view", "create")
MODEL_ACTIONS["rejection"] = ("view",)
MODEL_ACTIONS["deidentifier"] = ("view", "run", "notify")
MODEL_ACTIONS["project"] = PERMISSION_ACTIONS + ("workspace", "manage")
MODEL_ACTIONS["zone2"] = ("prepare", "review")
MODEL_ACTIONS["consent"] = ("view", "update")
MODEL_ACTIONS["redcap"] = ("view", "import", "export")
MODEL_ACTIONS["abstraction"] = PERMISSION_ACTIONS + ("manage",)
MODEL_ACTIONS["security"] = ("view", "manage")
MODEL_ACTIONS["files"] = (
    "read",
    "upload",
    "download",
    "delete",
    "reject",
    "view_original",
    "grant_original",
    "view_deidentified",
    "metadata",
    "deid_metadata",
)

FILE_VIEW_PERMISSIONS = (
    "files:view_original",
    "files:view_deidentified",
    "files:metadata",
    "files:deid_metadata",
)

KNOWN_PERMISSIONS = frozenset(
    f"{model}:{action}" for model, actions in MODEL_ACTIONS.items() for action in actions
)

RETIRED_PERMISSIONS = frozenset({"log:update", "log:delete"})


def known_only(permissions):
    return [p for p in permissions if p in KNOWN_PERMISSIONS]
