## 1. Directory Structure

```
mvp_sim/
├── core/
│   ├── __init__.py
│   ├── driver.py          # driver class
│   ├── environment.py     # distance, zones, id to object dicts
│   ├── order.py           # order class
│   ├── restaurant.py      # order tracking within restaurant
│   └── zone.py            # restaurants, idle / busy drivers
├── experiments/
│   └── baseline.py        # Currently (4/30/2026) star graph, TODO should be refactored
├── logger/
│   └── logger.py          # prints logs to terminal, TODO file based logs
├── metrics/
│   └── distance.py        # distance base, TODO could be refactored into experiments
├── policies/
│   ├── __init__.py
│   ├── base.py            # base class (tick)
│   └── star_policies.py   # policies specifically designed for star graphs (EAF, ERF)
├── simulator/
│   ├── __init__.py
│   ├── engine.py          # Core discrete-event loop
│   ├── event_handler.py   # handler for every event
│   └── events.py          # classes representing each type of discrete event
├── statistics/            # TODO
└── tests/                 # TODO
```

## 2. How it works
Simulation parameters are set up in the experiment folder.
These include the distance function, how restaurants are placed (zone and position),
where drivers start, how orders arrive, what policy is being used, etc

Once a simulation is running, the engine pops the next discrete event (events
with the same timestamp are deterministically ordered by their unique ids).
The event_handler then handles the event, shuffling drivers and orders around
as needed.
After the event is handled, the event_handler uses its logger to log the results
After that, the policy is alerted to what event happened, and can respond by
putting an event in the queue, calling the event_handler to immediately handle
a new event, or do nothing.
This repeats until there are no more events in the queue (NOTE: this could happen
while there are still undelivered orders if the policy is bad).

Most events trigger other events, though some stem from the policy
These chains go as follows

Order_Arrive -> Order_Ready
Policy -> Order_Assign -> Driver_Arrive -> Order_Delivered
Policy -> Policy_Wait
Policy -> Driver_Reposition_Assign -> Driver_Reposition_Arrive