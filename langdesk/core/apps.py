from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CoreConfig(AppConfig):
    name = "langdesk.core"
    verbose_name = "Langdesk"

    def ready(self) -> None:
        post_migrate.connect(ensure_groups, sender=self, dispatch_uid="langdesk-ensure-groups")


ROSTER_MODELS = [
    "language",
    "location",
    "department",
    "interpreter",
    "interpreterlanguage",
    "availabilitywindow",
    "timeoff",
]
READ_ONLY = {
    "scheduling": ["interpreterrequest", "offer", "requestevent"],
    "messaging": ["notification", "inboundmessage"],
}


def ensure_groups(sender, apps=None, using="default", **kwargs) -> None:
    """Create the two role groups and give coordinators roster permissions in the admin."""
    from django.apps import apps as global_apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.auth.models import Group, Permission

    from .roles import COORDINATORS, REQUESTERS

    for label in ("roster", "scheduling", "messaging"):
        create_permissions(global_apps.get_app_config(label), verbosity=0, using=using)

    coordinators, _ = Group.objects.using(using).get_or_create(name=COORDINATORS)
    Group.objects.using(using).get_or_create(name=REQUESTERS)

    codenames = [
        f"{action}_{model}"
        for model in ROSTER_MODELS
        for action in ("add", "change", "delete", "view")
    ]
    perms = list(
        Permission.objects.using(using).filter(
            content_type__app_label="roster", codename__in=codenames
        )
    )
    for app_label, models in READ_ONLY.items():
        perms += list(
            Permission.objects.using(using).filter(
                content_type__app_label=app_label,
                codename__in=[f"view_{model}" for model in models],
            )
        )
    coordinators.permissions.add(*perms)
