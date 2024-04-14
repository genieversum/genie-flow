from jinja2 import Template

OPENING = Template("Welcome to this interview. Please enter your work order summary.")

AI_EXTRACT_ACTIVITY_TYPE = Template(
    """
    You are an interviewer and want to extract the activity type 
    from a work order summary.
    
    The summary is given below.
    
    Possible activity types are
    - leak: any work considering a leak, for instance detecting or fixing a leak
    - paint: any work considering the paint on the meter, for instance painting the meter
    - other: any work that does not fall in any of the above categories
    
    Please interpret the following work order and match the most appropriate
    activity type.
    
    Work Order Summary
    ---
    {{user_input}}  
    """
)

USER_VERIFIES_ACTIVITY_TYPE = Template(
    """
    I have identified the activity type to be '{{activity_type}}'. Is this correct?
    If this is not correct, please let me know and tell me what the correct 
    activity type should be. 
    """
)

AI_EXTRACT_ACTIVITY_TYPE_VERIFICATION = Template(
    """
    Extract from the following user comment if they agree with my previous statement
    or not. If they didn't agree with my previous statement, they should provide
    an activity type. Possible activity types are
    - leak: any work considering a leak, for instance detecting or fixing a leak
    - paint: any work considering the paint on the meter, for instance painting the meter
    - other: any work that does not fall in any of the above categories
    
    If the user agrees with my previous statement, just state YES.
    If they user did not agree with my previous statement, just respond with
    ACTIVITY_TYPE followed by the activity type they provided.
    If they did not provide an alternative activity type, respond with NOT_PROVIDED.
    
    User Comment
    ___
    {{user_input}}
    """
)

USER_ENTERS_ACTIVITY_TYPE = Template(
    """
    I could not determine the alternative activity type you entered. Possible activity types are
    - leak: any work considering a leak, for instance detecting or fixing a leak
    - paint: any work considering the paint on the meter, for instance painting the meter
    - other: any work that does not fall in any of the above categories
    
    What was the activity type of the work order?
    """
)

AI_EXTRACTS_DETAILS = Template(
    """
    I found the following details:
    
    {{work_order_summary}}
    """
)

USER_VERIFIES_DETAILS = Template(
    """
    I have recorded the details below. Please indicate if these are correct and complete.
    
    leak details:
    {{leak_details}}
    
    paint details:
    {{paint_details}}
    """
)

AI_EXTRACTS_DETAILS_VERIFICATION = Template(
    """
    is this a YES or a NO
    """
)

USER_ENTERS_ADDITIONAL_DETAILS = Template(
    """
    Please enter the additional details.
    """
)

AI_EXTRACTS_ADDITIONAL_DETAILS = Template(
    """
    Interpret the additional details.
    """
)