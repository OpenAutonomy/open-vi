"""UCI/A-GRA message-type names used on the bus.

Handlers, publishers, and tests import these names. They do not
import each other for ``MT_*`` constants. Adapters map a name to
``/topic/<MessageType>`` in :mod:`open_vi.asb.topics`.
"""

from __future__ import annotations

# Flight command / activity
MT_FLIGHT_COMMAND = "MA_FlightCommand"
MT_FLIGHT_COMMAND_STATUS = "MA_FlightCommandStatus"
MT_FLIGHT_ACTIVITY = "MA_FlightActivity"

# Capability / control offer
MT_FLIGHT_CAPABILITY = "MA_FlightCapability"
MT_FLIGHT_CAPABILITY_STATUS = "MA_FlightCapabilityStatus"
MT_CONTROL_STATUS = "ControlStatus"

# Control assignment
MT_CONTROL_REQUEST = "MA_ControlRequest"
MT_CONTROL_REQUEST_STATUS = "MA_ControlRequestStatus"
MT_CONTROL_ASSIGNMENT = "MA_ControlAssignment"

# Route ladder / File*
MT_ACTIVATION_COMMAND = "MA_MissionPlanActivationCommand"
MT_ACTIVATION_STATUS = "MA_MissionPlanActivationCommandStatus"
MT_ROUTE_PLAN = "MA_RoutePlan"
MT_FILE_LOCATION = "FileLocation"
MT_FILE_METADATA = "FileMetadata"
MT_ROUTE_VALIDATION_COMMAND = "RoutePlanValidationCommand"
MT_ROUTE_VALIDATION = "RoutePlanValidation"
MT_ROUTE_VALIDATION_STATUS = "RoutePlanValidationCommandStatus"

# Plan execution / activation state
MT_MISSION_PLAN_ACTIVATION_STATUS = "MissionPlanActivationStatus"
MT_RESPONSE_PLAN_EXECUTION_STATUS = "ResponsePlanExecutionStatus"
MT_ROUTE_PLAN_EXECUTION_STATUS = "RoutePlanExecutionStatus"
MT_MISSION_PLAN_EXECUTION_STATUS = "MA_MissionPlanExecutionStatus"
MT_ACTIVITY_PLAN_EXECUTION_STATUS = "ActivityPlanExecutionStatus"
MT_ROUTE_ACTIVITY_PLAN_EXECUTION_STATUS = "RouteActivityPlanExecutionStatus"
MT_TASK_PLAN_EXECUTION_STATUS = "TaskPlanExecutionStatus"

# Heartbeat / status
MT_SERVICE_STATUS = "ServiceStatus"
MT_SERVICE_STATUS_DATA_REQUEST = "ServiceStatusDataRequest"
MT_SERVICE_STATUS_DATA_REQUEST_STATUS = "ServiceStatusDataRequestStatus"
MT_SUBSYSTEM_STATUS = "SubsystemStatus"
MT_SUBSYSTEM_STATUS_DATA_REQUEST = "SubsystemStatusDataRequest"
MT_SUBSYSTEM_STATUS_DATA_REQUEST_STATUS = "SubsystemStatusDataRequestStatus"
MT_MA_FAULT = "MA_Fault"

# Vehicle state
MT_POSITION_REPORT_DETAILED = "MA_PositionReportDetailed"
MT_WEATHER_OBSERVATION = "WeatherObservation"
MT_NAVIGATION_REPORT = "NavigationReport"
MT_COMPONENT_STATUS = "ComponentStatus"

# Query / airfield
MT_QUERY_DATA_REQUEST = "QueryDataRequest"
MT_QUERY_DATA_REQUEST_STATUS = "QueryDataRequestStatus"
MT_AIRFIELD_REPORT = "AirfieldReport"

# Task
MT_TASK_COMMAND = "MA_TaskCommand"
MT_TASK_COMMAND_STATUS = "MA_TaskCommandStatus"
MT_TASK_STATUS = "TaskStatus"
MT_MA_TASK = "MA_Task"

# Failsafe / notification
MT_MA_RESPONSE = "MA_Response"
MT_SYSTEM_NOTIFICATION = "MA_SystemNotification"

# System management
MT_SYSTEM_MGMT_REQUEST = "MA_SystemManagementRequest"
MT_SYSTEM_MGMT_STATUS = "MA_SystemManagementRequestStatus"

__all__ = [
    "MT_ACTIVATION_COMMAND",
    "MT_ACTIVATION_STATUS",
    "MT_ACTIVITY_PLAN_EXECUTION_STATUS",
    "MT_AIRFIELD_REPORT",
    "MT_COMPONENT_STATUS",
    "MT_CONTROL_ASSIGNMENT",
    "MT_CONTROL_REQUEST",
    "MT_CONTROL_REQUEST_STATUS",
    "MT_CONTROL_STATUS",
    "MT_FILE_LOCATION",
    "MT_FILE_METADATA",
    "MT_FLIGHT_ACTIVITY",
    "MT_FLIGHT_CAPABILITY",
    "MT_FLIGHT_CAPABILITY_STATUS",
    "MT_FLIGHT_COMMAND",
    "MT_FLIGHT_COMMAND_STATUS",
    "MT_MA_FAULT",
    "MT_MA_RESPONSE",
    "MT_MA_TASK",
    "MT_MISSION_PLAN_ACTIVATION_STATUS",
    "MT_MISSION_PLAN_EXECUTION_STATUS",
    "MT_NAVIGATION_REPORT",
    "MT_POSITION_REPORT_DETAILED",
    "MT_QUERY_DATA_REQUEST",
    "MT_QUERY_DATA_REQUEST_STATUS",
    "MT_RESPONSE_PLAN_EXECUTION_STATUS",
    "MT_ROUTE_ACTIVITY_PLAN_EXECUTION_STATUS",
    "MT_ROUTE_PLAN",
    "MT_ROUTE_PLAN_EXECUTION_STATUS",
    "MT_ROUTE_VALIDATION",
    "MT_ROUTE_VALIDATION_COMMAND",
    "MT_ROUTE_VALIDATION_STATUS",
    "MT_SERVICE_STATUS",
    "MT_SERVICE_STATUS_DATA_REQUEST",
    "MT_SERVICE_STATUS_DATA_REQUEST_STATUS",
    "MT_SUBSYSTEM_STATUS",
    "MT_SUBSYSTEM_STATUS_DATA_REQUEST",
    "MT_SUBSYSTEM_STATUS_DATA_REQUEST_STATUS",
    "MT_SYSTEM_MGMT_REQUEST",
    "MT_SYSTEM_MGMT_STATUS",
    "MT_SYSTEM_NOTIFICATION",
    "MT_TASK_COMMAND",
    "MT_TASK_COMMAND_STATUS",
    "MT_TASK_PLAN_EXECUTION_STATUS",
    "MT_TASK_STATUS",
    "MT_WEATHER_OBSERVATION",
]
