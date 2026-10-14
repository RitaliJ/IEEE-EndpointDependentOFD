# Jin TODO

arrival - jin
config - jin
cost - jin 
driver_init - jin

figure out core design diffs between arrival, config, cost, driver_init between unified_sim and the mvp_sim and then figure out what we want to keep

## arrival:

- remove OrderSpec,
- Keep Order dataclass in /home/jinhuangzhou/cs145/unified_sim/core/order.py
- may be good to keep the delivered function from old/mvp_sim/core/order.py and port it into unified_sim/core/order.py


there's only 1 arrival generator in mvp_sim/experiments/baseline.py,

don't really like it so gonna change it to fit more of the arrival in unified

redo arrivals so that its configurable:
- have a line in the config for what type of arrival gen func to use for each resturant: (either all resturants have the same, or specifiy groupings of resturants to be different: poisson: {r1, r2, r3}; uniform: {r4, r5, r6}), then use it to generate a bunch of orders based on a set time death and then ues that as the initial? 

- real_data.py shouldn't be in arrival/ we should make it its own thing and also a configurable flag: real_data : True/False,

it's also just wrong, since zones are from accept_gps and not delivery_gps

### need a zone clustering policy so that it can cluster resturants into zones in a certain way

If True, still use the synthetic arrivals but the following changes:

### drivers
### resturants (init positions)
### driver init positions
### zones

it'll pass these params to like how run_experiment() in run_expeimern.py in unified does it

maybe keep build_environment_from_csv, but allow the user to specify what the generator to use for each resturant, so user needs to run a real_data_csv scan first to konw that info: # drirvers, # resturants, # zones by kmeans or can use other zone clustering policies

## config

schema.py is a good idea that mvp_sim did not have so we need to incoporate this into mvp_sim, this is tied to the experiments/

yes:
master_seed
num_drivers
num_zones
num_resturants
                useful if just want a defalut number
simulation_duration
warm_up_duration
policy
                specified name and the creator will try to find the file name
                
                
                set("eaf" ... )
zone_simplification
                true or false bool, if true uses cost_function/dist_function that is associated with the zone's centriods instead of pure locations;

                event handler uses dist_function to convert euclidean locations to some time metric? 

                policy could use both cost_function and dist_function as a way to keep track of any statistics that it needs to make decisions?

                for example:
                euclidean_cost_point
                    vs
                euclidean_cost_zone

                if this is true then zone_layout needs to be sepcified

zone_layout
                a map of zones and the resturants it contains; if not one of the given options then it needs to be expliclty set

                example:

                set("uniform" or whatever): (uniform, uniform_param)

                or 

                {
                    zone_1 : {resturatn_1} ...
                }

cost_function
                uses the dist_function to help figure out the real cost
                
                takes in a list of orders

                this is utliatmely the cost of the delivery, cause we can alwasy scale it by any factors, but its the time it takes to deliver the order and how much more efficient, batching others for delivery is, becuase then it should be simplified to like, if multiple deliveries then the next one is easier or if in same zone then the delivery time sublinear or scaled down somehow...

                this is the core of the simulator/problem

                the distance value of moving from one location to another; converts distance to time when calcuating arrival time of orders and flow time

                can be zone based for sure

                how to make batching/zoning easier in this form?

                orders can have a batch_number, or the function can just tkae in a list of orders, orders have a sourcec and a dest, so if multiple in the list then modify the arrival time based on that fact.



dist_function
                takes in two locs, and then calculates the distance between teh two

                euclidean 

arrival_generation
                either from the set of options or need to be specified

                set("poisson with a lambda" ..) or a map

                generator_type: (poisson, lambda)
                
                ex:

                {poisson: (lambda, {resturant_1, resutrant_2})}

prep_time_generator
                sampels from a distribution for prep time on a order, can be None

                generator_type: [resturant_ids]
                
                ex:

                poisson: (lambda, {resturant_1, resutrant_2})

driver_init
                from a set of allowed and inputted as a tuple or as an explicit dict

                (uniform, uniform param)

                vs

                {
                    d1: (x,y), zone
                    ...
                }

queue_capcity
                None
                vs
                (500) for all
                vs
                {
                    resturant1: 100
                }

deadline_enabled
                a true or false

                orders can be dropped

statistics
                chosen from the list of files in statistics/




#### real data stuff:
zone_clustering_policy
                k means or smt else

data_path

time_scale
                how to condense the real wolrd time scale to simmulation time scale



no:
policy_bundle
                feels redundant
two_step_routing
                this should be policy decision. Policy can use DriverRepositionAssignEvent to either do zone centroid as location if repositoin to zone, or use location of resturant and inherit the resturant's zone
empty_wait_W
                should not be a thing if accounting is done right and policy has full control over when to wait a driver if the resturant has no orders

cost_c
                not necssary because it can be defined in each cost/dist function itself

cost_alpha
                same as above

### keep the from-yaml function

### zone class should also have a zone centriod / location



## cost

base.py
profit_adjusted.py
travel_time.py

all of this isn't good

we can just have two files:
cost_functions.py
dist_functions.py

and have both be monolith classes with diff functions in them and then use it like:

env.cost_fun = CostFunction.cost

env.cost_fun(loc_a, loc_b)

## driver_init

proportional_init.py is stupid

explicit_init is good

random_init is good, might want uniform as well or something similar? but also have a statmenet beign like can't do unfirom if u give me 1 driver and 5 resturants or something like that or 1 driver and 5 zones