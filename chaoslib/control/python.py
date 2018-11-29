# -*- coding: utf-8 -*-
from copy import deepcopy
import importlib
import inspect
import os
import os.path
import sys
import traceback
from typing import Any, Callable, Dict, List, Union

from logzero import logger

from chaoslib import substitute
from chaoslib.exceptions import ActivityFailed, ChaosException, \
    InvalidActivity, InvalidControl
from chaoslib.types import Activity, Configuration, Control, Experiment, \
    Journal, Run, Secrets


__all__ = ["apply_python_control", "cleanup_control", "initialize_control",
           "validate_python_control"]
_level_mapping = {
    "experiment-before": "before_experiment_control",
    "experiment-after": "after_experiment_control",
    "hypothesis-before": "before_hypothesis_control",
    "hypothesis-after": "after_hypothesis_control",
    "method-before": "before_method_control",
    "method-after": "after_method_control",
    "rollback-before": "before_rollback_control",
    "rollback-after": "after_rollback_control",
    "activity-before": "before_activity_control",
    "activity-after": "after_activity_control",
}


def initialize_control(control: Control, configuration: Configuration,
                       secrets: Secrets):
    """
    Initialize a control by calling its `configure_control` function.
    """
    func = load_func(control, "configure_control")
    if not func:
        return
    func(configuration, secrets)


def cleanup_control(control: Control):
    """
    Cleanup a control by calling its `cleanup_control` function.
    """
    func = load_func(control, "cleanup_control")
    if not func:
        return
    func()


def validate_python_control(control: Control):
    """
    Verify that a control block matches the specification
    """
    if "name" not in control:
        raise InvalidControl("A control must have a `name` property")

    name = control["name"]
    if "provider" not in control:
        raise InvalidControl(
            "Control '{}' must have a `provider` property".format(name))

    provider = control["provider"]
    mod_name = control.get("module")
    if not mod_name:
        raise InvalidActivity(
            "Control '{}' must have a module path".format(name))

    try:
        importlib.import_module(mod_name)
    except ModuleNotFoundError:
        raise InvalidActivity("could not find Python module '{mod}' "
                              "in control '{name}'".format(
                                  mod=mod_name, name=name))


def apply_python_control(level: str, control: Control,
                         context: Union[Activity, Experiment],
                         state: Union[Journal, Run, List[Run]] = None,
                         configuration: Configuration = None,
                         secrets: Secrets = None):
    """
    Apply a control by calling a function matching the given level.
    """
    provider = control["provider"]
    func_name = _level_mapping.get(level)
    func = load_func(control, func_name)
    if not func:
        return

    arguments = deepcopy(provider.get("arguments", {}))

    if configuration or secrets:
        arguments = substitute(arguments, configuration, secrets)

    sig = inspect.signature(func)
    if "secrets" in provider and "secrets" in sig.parameters:
        arguments["secrets"] = {}
        for s in provider["secrets"]:
            arguments["secrets"].update(secrets.get(s, {}).copy())

    if "configuration" in sig.parameters:
        arguments["configuration"] = configuration.copy()

    if "state" in sig.parameters:
        arguments["state"] = state

    func(context=context, **arguments)


###############################################################################
# Internals
###############################################################################
def load_func(control: Control, func_name: str) -> Callable:
    provider = control["provider"]
    mod_path = provider["module"]
    try:
        mod = importlib.import_module(mod_path)
    except ModuleNotFoundError as x:
        logger.debug(
            "Control module '{}' could not be loaded. "
            "Have you installed it?".format(mod_path))
        return
    func = getattr(mod, func_name, None)
    if not func:
        logger.debug(
            "Control module '{}' does not declare '{}'".format(
                mod_path, func_name
            ))
        return

    try:
        logger.debug(
            "Control '{}' loaded from '{}'".format(
                func_name, inspect.getfile(func)))
    except TypeError:
        pass

    return func