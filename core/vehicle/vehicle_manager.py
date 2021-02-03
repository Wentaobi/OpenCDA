# -*- coding: utf-8 -*-

"""A class manager to embed different plugins with vehicle
"""
# Author: Runsheng Xu <rxx3386@ucla.edu>
# License: MIT

import uuid
import weakref

from core.agents.navigation.platoon_behavior_agent import PlatooningBehaviorAgent
from core.platooning.platooning_plugin import PlatooningPlugin
from core.platooning.fsm import FSM


class VehicleManager(object):
    """
    A class manager to embed different modules with vehicle together
    """

    def __init__(self, vehicle, world, behavior='normal', communication_range=35,
                 buffer_size=5, sample_resolution=4.5, cda_enabled=True, status=FSM.MAINTINING,
                 ignore_traffic_light=False, debug_trajectory=False, debug=False):
        """
        Construct class
        :param vehicle: carla Actor
        :param world: platooning world object
        :param behavior: driving style.
        :param communication_range:
        :param buffer_size: queue size for behavior planning
        :param sample_resolution: the minimum distance between any waypoint in the routing
        :param cda_enabled:  whether the vehicle equipped with cda feature
        """
        self.vid = str(uuid.uuid1())
        self.destination = None

        self.vehicle = vehicle
        self.agent = PlatooningBehaviorAgent(vehicle, behavior=behavior, ignore_traffic_light=ignore_traffic_light,
                                             buffer_size=buffer_size, sampling_resolution=sample_resolution,
                                             debug_trajectory=debug_trajectory, debug=debug)

        self._platooning_plugin = PlatooningPlugin(cda_enabled, status=status, search_range=communication_range)

        world.update_vehicle_manager(self)
        self.world = weakref.ref(world)()

    def set_platooning(self, platooning_object, platooning_id, in_team_id, lead=False):
        """
        Called when vehicle joined/formed a platooning
        :param in_team_id:
        :param lead:
        :param platooning_object: the platooning object
        :param platooning_id:
        :return:
        """
        self._platooning_plugin.platooning_id = platooning_id
        self._platooning_plugin.in_platooning = True
        self._platooning_plugin.platooning_object = weakref.ref(platooning_object)()
        self._platooning_plugin.id_in_team = in_team_id

        if lead:
            self._platooning_plugin.take_charge()

    def get_platooning_status(self):
        """
        Check whether the vehicle in the platooning
        :return:
        """
        return self._platooning_plugin.in_platooning, self._platooning_plugin.platooning_id, \
               self._platooning_plugin.platooning_object

    def get_fsm_status(self):
        """
        return the fsm status
        :return:
        """
        return self._platooning_plugin.status

    def set_platooning_status(self, status):
        """
        Set the platooning status
        :param status:
        :return:
        """
        self._platooning_plugin.status = status

    def update_info(self, world, frontal_vehicle=None):
        """
        Update the world and platooning information
        :param world:
        :param frontal_vehicle:
        :return:
        """
        self.agent.update_information(world, frontal_vehicle)

    def run_step(self):
        """
        Execute one step of navigation based on platooning status
        :return:
        """
        # TODO: Right now take lead is not in consideration
        if not self._platooning_plugin.in_platooning:
            # if the ego-vehicle is still searching for platooning
            if self._platooning_plugin.status == FSM.SEARCHING:
                # get ready to move to the point if platooning found
                self.set_platooning_status(FSM.MOVE_TO_POINT) \
                 if self._platooning_plugin.platooning_search(self.vid, self.world, self.vehicle.get_location()) \
                 else self.set_platooning_status(FSM.SEARCHING)

                return self.agent.run_step()

            elif self._platooning_plugin.status == FSM.MOVE_TO_POINT:
                control, ready_to_join = self.agent.run_step_move2point(self._platooning_plugin.front_vehicle,
                                                                        self._platooning_plugin.rear_vechile)
                if ready_to_join:
                    self.set_platooning_status(FSM.JOINING)
                return control

            elif self._platooning_plugin.status == FSM.JOINING:
                control, joining_finished = self.agent.run_step_joining(self._platooning_plugin.front_vehicle)
                if joining_finished:
                    _, _, platooning_manager = self._platooning_plugin.front_vehicle.get_platooning_status()
                    # TODO: If cut-in joining, the whole list may need reorder
                    platooning_manager.add_member(self)
                    self.set_platooning_status(FSM.MAINTINING)
                return control

        else:
            if self._platooning_plugin.leader:
                control = self.agent.run_step()
            # TODO: ADD OPENGAP LATER FOR cut-in joining
            else:
                control = self.agent.run_step_maintaining()

            return control