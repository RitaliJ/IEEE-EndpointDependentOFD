# OBJECTIVE FUNCTIONS HERE ARE SEEN BY THE POLICY
# event handler focuses on the travel_time.py to figure out event time ticks
# policies are trying to see objective to figure out what to minimize

# this doesn't just look at the raw distance/time costs but weights them by 
# some objective function

# EXAMPLES TO IMPLEMENT:
# urgency dependent cost function (e.g. time cost is more important for urgent 
# deliveries)
# note that average flow time, max flow time, etc go into STATISTICS to compare 
# the policies
# nevertheless some kind of flow time mention could be used in the objective 
# function to encourage the policy to minimize it
