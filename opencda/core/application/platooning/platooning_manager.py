# -*- coding: utf-8 -*-

"""Platooning Manager
"""

# Author: Runsheng Xu <rxx3386@ucla.edu>
# License: MIT

import uuid
import weakref

import carla
import matplotlib.pyplot as plt
import numpy as np

import opencda.core.plan.drive_profile_plotting as open_plt


class PlatooningManager(object):
    """
    Platooning manager for vehicle managers
    """

    def __init__(self, config_yaml, cav_world):
        """
        Construct class
        :param config_yaml:
        :param cav_world: CAV world object
        """
        self.pmid = str(uuid.uuid1())

        self.vehicle_manager_list = []
        self.maximum_capacity = config_yaml['max_capacity']

        self.destination = None
        self.center_loc = None

        # this is used to control platooning speed during joining
        self.leader_target_speed = 0
        self.origin_leader_target_speed = 0
        self.recover_speed_counter = 0

        cav_world.update_platooning(self)
        self.cav_world = weakref.ref(cav_world)()

    def set_lead(self, vehicle_manager):
        """
        Set the leader of the platooning
        :param vehicle_manager:
        :return:
        """
        self.add_member(vehicle_manager, leader=True)

        # this variable is used to control leader speed
        self.origin_leader_target_speed = vehicle_manager.agent.max_speed - vehicle_manager.agent.speed_lim_dist

    def add_member(self, vehicle_manager, leader=False):
        """
        Add memeber to the current platooning
        :param leader: whether this cav is a leader
        :param vehicle_manager:
        :return:
        """
        self.vehicle_manager_list.append(vehicle_manager)
        vehicle_manager.v2x_manager.set_platoon(len(self.vehicle_manager_list)-1,
                                                platooning_object=self,
                                                platooning_id=self.pmid,
                                                leader=leader)

    def set_member(self, vehicle_manager, index, lead=False):
        """
        Set member at specific index
        :param lead:
        :param vehicle_manager:
        :param index:
        :return:
        """
        self.vehicle_manager_list.insert(index, vehicle_manager)
        vehicle_manager.v2x_manager.set_platoon(index,
                                                platooning_object=self,
                                                platooning_id=self.pmid,
                                                leader=lead)

    def cal_center_loc(self):
        """
        Calculate center location of the platoon
        :return:
        """
        v1_ego_transform = self.vehicle_manager_list[0].localizer.get_ego_pos()
        v2_ego_transform = self.vehicle_manager_list[-1].localizer.get_ego_pos()

        self.center_loc = carla.Location(x=(v1_ego_transform.location.x + v2_ego_transform.location.x)/2,
                                         y=(v1_ego_transform.location.y + v2_ego_transform.location.y)/2,
                                         z=(v1_ego_transform.location.z + v2_ego_transform.location.z)/2)

    def update_member_order(self):
        """
        Update the members' front and rear vehicle.
        This should be called whenever new member added to the platoon list
        :return:
        """
        for i, vm in enumerate(self.vehicle_manager_list):
            if i != 0:
                vm.v2x_manager.set_platoon(i, leader=False)
                vm.v2x_manager.set_platoon_front(self.vehicle_manager_list[i-1])
            if i != len(self.vehicle_manager_list)-1:
                leader = True if i == 0 else False
                vm.v2x_manager.set_platoon(i, leader=leader)
                vm.v2x_manager.set_platoon_rear(self.vehicle_manager_list[i+1])

    def reset_speed(self):
        """
        After joining request accepted for certain steps, the platoon will return to the origin speed.
        :return:
        """
        if self.recover_speed_counter <= 0:
            self.leader_target_speed = self.origin_leader_target_speed
        else:
            self.recover_speed_counter -= 1

    def response_joining_request(self, request_loc):
        """
        Identify whether to accept the joining request based on capacity.
        Args:
            request_loc (carla.Location): request vehicle location.

        Returns:

        """
        if len(self.vehicle_manager_list) >= self.maximum_capacity:
            return False
        else:
            # when the platoon accept a joining request,by default it will decrease the speed
            # so the merging vehicle can better catch up with
            self.leader_target_speed = self.origin_leader_target_speed - 5
            self.recover_speed_counter = 200

            # find the corresponding vehicle manager and add it to the leader's whitelist
            request_vm = self.cav_world.locate_vehicle_manager(request_loc)
            self.vehicle_manager_list[0].agent.add_white_list(request_vm)

            return True

    def set_destination(self, destination):
        """
        Set desination of the vehicle managers in the platoon.
        TODO: Currently we assume all vehicles in a platoon will have the same destination
        :return:
        """
        self.destination = destination
        for i in range(len(self.vehicle_manager_list)):
            self.vehicle_manager_list[i].set_destination(
                self.vehicle_manager_list[i].vehicle.get_location(), destination, clean=True)

    def update_information(self):
        """
        Update CAV world information for every member in the list.
        :return:
        """
        self.reset_speed()
        for i in range(len(self.vehicle_manager_list)):
            self.vehicle_manager_list[i].update_info()
        # update the center location of the platoon
        self.cal_center_loc()

    def run_step(self):
        """
        Run a step for each vehicles.
        :return:
        """
        control_list = []
        for i in range(len(self.vehicle_manager_list)):
            control = self.vehicle_manager_list[i].run_step(self.leader_target_speed)
            control_list.append(control)

        for (i, control) in enumerate(control_list):
            self.vehicle_manager_list[i].vehicle.apply_control(control)

        return control_list

    def evaluate(self):
        # used to save all members' statistics
        velocity_list = []
        acceleration_list = []
        time_gap_list = []
        distance_gap_list = []

        perform_txt = ''

        for i in range(len(self.vehicle_manager_list)):
            vm = self.vehicle_manager_list[i]
            debug_helper = vm.agent.debug_helper

            # we need to filter out the first 100 data points since the vehicles
            # spawn at the beginning have no velocity and thus make the time gap close to infinite

            velocity_list += debug_helper.speed_list
            acceleration_list += debug_helper.acc_list
            time_gap_list += debug_helper.time_gap_list
            distance_gap_list += debug_helper.dist_gap_list

            time_gap_list_tmp = np.array(debug_helper.time_gap_list)
            time_gap_list_tmp = time_gap_list_tmp[time_gap_list_tmp < 100]
            distance_gap_list_tmp = np.array(debug_helper.dist_gap_list)
            distance_gap_list_tmp = distance_gap_list_tmp[distance_gap_list_tmp < 100]

            perform_txt += '\n Platoon member ID:%d, Actor ID:%d : \n' % (i, vm.vehicle.id)
            perform_txt += 'Time gap mean: %f, std: %f \n' % (np.mean(time_gap_list_tmp),
                                                              np.std(time_gap_list_tmp))
            perform_txt += 'Distance gap mean: %f, std: %f \n' %(np.mean(distance_gap_list_tmp),
                                                                 np.std(distance_gap_list_tmp))

        figure = plt.figure()

        plt.subplot(411)
        open_plt.draw_velocity_profile_single_plot(velocity_list)

        plt.subplot(412)
        open_plt.draw_acceleration_profile_single_plot(acceleration_list)

        plt.subplot(413)
        open_plt.draw_time_gap_profile_singel_plot(time_gap_list)

        plt.subplot(414)
        open_plt.draw_dist_gap_profile_singel_plot(distance_gap_list)

        label = []
        for i in range(1, len(velocity_list) + 1):
            label.append('Leading Vehicle, id: %d' % int(i - 1) if i == 1 else 'Platoon member, id: %d' % int(i - 1))

        figure.legend(label, loc='upper right')

        return figure, perform_txt

    def destroy(self):
        """
        Destroy vehicles
        :return:
        """
        for vm in self.vehicle_manager_list:
            vm.destroy()
