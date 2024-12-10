import gymnasium as gym
import imageio
import matplotlib.pyplot as plt
import numpy as np
from pyquaternion import Quaternion

from gym_so100.constants import SIM_EPISODE_LENGTH


class BasePolicy:
    def __init__(self, inject_noise=False):
        self.inject_noise = inject_noise
        self.step_count = 0
        self.left_trajectory = None
        self.right_trajectory = None

    def generate_trajectory(self, observation: dict):
        raise NotImplementedError

    @staticmethod
    def interpolate(curr_waypoint, next_waypoint, t):
        t_frac = (t - curr_waypoint["t"]) / (next_waypoint["t"] - curr_waypoint["t"])
        curr_xyz = curr_waypoint["xyz"]
        curr_quat = curr_waypoint["quat"]
        curr_grip = curr_waypoint["gripper"]
        next_xyz = next_waypoint["xyz"]
        next_quat = next_waypoint["quat"]
        next_grip = next_waypoint["gripper"]
        xyz = curr_xyz + (next_xyz - curr_xyz) * t_frac
        quat = curr_quat + (next_quat - curr_quat) * t_frac
        gripper = curr_grip + (next_grip - curr_grip) * t_frac
        return xyz, quat, gripper

    def __call__(self, observation):
        # generate trajectory at first timestep, then open-loop execution
        if self.step_count == 0:
            self.generate_trajectory(observation)

        # obtain left and right waypoints
        if self.left_trajectory[0]["t"] == self.step_count:
            self.curr_left_waypoint = self.left_trajectory.pop(0)
        next_left_waypoint = self.left_trajectory[0]

        if self.right_trajectory[0]["t"] == self.step_count:
            self.curr_right_waypoint = self.right_trajectory.pop(0)
        next_right_waypoint = self.right_trajectory[0]

        # interpolate between waypoints to obtain current pose and gripper command
        left_xyz, left_quat, left_gripper = self.interpolate(
            self.curr_left_waypoint, next_left_waypoint, self.step_count
        )
        right_xyz, right_quat, right_gripper = self.interpolate(
            self.curr_right_waypoint, next_right_waypoint, self.step_count
        )

        # Inject noise
        if self.inject_noise:
            scale = 0.01
            left_xyz = left_xyz + np.random.uniform(-scale, scale, left_xyz.shape)
            right_xyz = right_xyz + np.random.uniform(-scale, scale, right_xyz.shape)

        action_left = np.concatenate([left_xyz, left_quat, [left_gripper]])
        action_right = np.concatenate([right_xyz, right_quat, [right_gripper]])

        self.step_count += 1
        return np.concatenate([action_left, action_right])


class PickAndTransferPolicy(BasePolicy):
    def generate_trajectory(self, observation):
        init_mocap_pose_right = observation["mocap_pose_right"]
        init_mocap_pose_left = observation["mocap_pose_left"]

        box_info = np.array(observation["env_state"])
        box_xyz = box_info[:3]
        # box_quat = box_info[3:]
        # print(f"Generate trajectory for {box_xyz=}")

        gripper_pick_quat = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat = gripper_pick_quat * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        meet_left_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)

        meet_xyz = np.array([0, 0.5, 0.25])

        self.left_trajectory = [
            {
                "t": 0,
                "xyz": init_mocap_pose_left[:3],
                "quat": init_mocap_pose_left[3:],
                "gripper": 0,
            },  # sleep
            {
                "t": 100,
                "xyz": meet_xyz + np.array([-0.1, 0, -0.02]),
                "quat": meet_left_quat.elements,
                "gripper": 1,
            },  # approach meet position
            {
                "t": 260,
                "xyz": meet_xyz + np.array([0.02, 0, -0.02]),
                "quat": meet_left_quat.elements,
                "gripper": 1,
            },  # move to meet position
            {
                "t": 310,
                "xyz": meet_xyz + np.array([0.02, 0, -0.02]),
                "quat": meet_left_quat.elements,
                "gripper": 0,
            },  # close gripper
            {
                "t": 360,
                "xyz": meet_xyz + np.array([-0.1, 0, -0.02]),
                "quat": np.array([1, 0, 0, 0]),
                "gripper": 0,
            },  # move left
            {
                "t": 400,
                "xyz": meet_xyz + np.array([-0.1, 0, -0.02]),
                "quat": np.array([1, 0, 0, 0]),
                "gripper": 0,
            },  # stay
        ]

        self.right_trajectory = [
            {
                "t": 0,
                "xyz": init_mocap_pose_right[:3],
                "quat": init_mocap_pose_right[3:],
                "gripper": 0,
            },  # sleep
            {
                "t": 90,
                "xyz": box_xyz + np.array([0, 0, 0.08]),
                "quat": gripper_pick_quat.elements,
                "gripper": 1,
            },  # approach the cube
            {
                "t": 130,
                "xyz": box_xyz + np.array([0, 0, -0.015]),
                "quat": gripper_pick_quat.elements,
                "gripper": 1,
            },  # go down
            {
                "t": 170,
                "xyz": box_xyz + np.array([0, 0, -0.015]),
                "quat": gripper_pick_quat.elements,
                "gripper": 0,
            },  # close gripper
            {
                "t": 200,
                "xyz": meet_xyz + np.array([0.05, 0, 0]),
                "quat": gripper_pick_quat.elements,
                "gripper": 0,
            },  # approach meet position
            {
                "t": 220,
                "xyz": meet_xyz,
                "quat": gripper_pick_quat.elements,
                "gripper": 0,
            },  # move to meet position
            {"t": 310, "xyz": meet_xyz, "quat": gripper_pick_quat.elements, "gripper": 1},  # open gripper
            {
                "t": 360,
                "xyz": meet_xyz + np.array([0.1, 0, 0]),
                "quat": gripper_pick_quat.elements,
                "gripper": 1,
            },  # move to right
            {
                "t": 400,
                "xyz": meet_xyz + np.array([0.1, 0, 0]),
                "quat": gripper_pick_quat.elements,
                "gripper": 1,
            },  # stay
        ]


class InsertionPolicy(BasePolicy):
    def generate_trajectory(self, observation):
        init_mocap_pose_right = observation["mocap_pose_right"]
        init_mocap_pose_left = observation["mocap_pose_left"]

        peg_info = np.array(observation["env_state"])[:7]
        peg_xyz = peg_info[:3]
        # peg_quat = peg_info[3:]

        socket_info = np.array(observation["env_state"])[7:]
        socket_xyz = socket_info[:3]
        # socket_quat = socket_info[3:]

        gripper_pick_quat_right = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_right = gripper_pick_quat_right * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        gripper_pick_quat_left = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_left = gripper_pick_quat_left * Quaternion(axis=[0.0, 1.0, 0.0], degrees=60)

        meet_xyz = np.array([0, 0.5, 0.15])
        lift_right = 0.00715

        self.left_trajectory = [
            {
                "t": 0,
                "xyz": init_mocap_pose_left[:3],
                "quat": init_mocap_pose_left[3:],
                "gripper": 0,
            },  # sleep
            {
                "t": 120,
                "xyz": socket_xyz + np.array([0, 0, 0.08]),
                "quat": gripper_pick_quat_left.elements,
                "gripper": 1,
            },  # approach the cube
            {
                "t": 170,
                "xyz": socket_xyz + np.array([0, 0, -0.03]),
                "quat": gripper_pick_quat_left.elements,
                "gripper": 1,
            },  # go down
            {
                "t": 220,
                "xyz": socket_xyz + np.array([0, 0, -0.03]),
                "quat": gripper_pick_quat_left.elements,
                "gripper": 0,
            },  # close gripper
            {
                "t": 285,
                "xyz": meet_xyz + np.array([-0.1, 0, 0]),
                "quat": gripper_pick_quat_left.elements,
                "gripper": 0,
            },  # approach meet position
            {
                "t": 340,
                "xyz": meet_xyz + np.array([-0.05, 0, 0]),
                "quat": gripper_pick_quat_left.elements,
                "gripper": 0,
            },  # insertion
            {
                "t": 400,
                "xyz": meet_xyz + np.array([-0.05, 0, 0]),
                "quat": gripper_pick_quat_left.elements,
                "gripper": 0,
            },  # insertion
        ]

        self.right_trajectory = [
            {
                "t": 0,
                "xyz": init_mocap_pose_right[:3],
                "quat": init_mocap_pose_right[3:],
                "gripper": 0,
            },  # sleep
            {
                "t": 120,
                "xyz": peg_xyz + np.array([0, 0, 0.08]),
                "quat": gripper_pick_quat_right.elements,
                "gripper": 1,
            },  # approach the cube
            {
                "t": 170,
                "xyz": peg_xyz + np.array([0, 0, -0.03]),
                "quat": gripper_pick_quat_right.elements,
                "gripper": 1,
            },  # go down
            {
                "t": 220,
                "xyz": peg_xyz + np.array([0, 0, -0.03]),
                "quat": gripper_pick_quat_right.elements,
                "gripper": 0,
            },  # close gripper
            {
                "t": 285,
                "xyz": meet_xyz + np.array([0.1, 0, lift_right]),
                "quat": gripper_pick_quat_right.elements,
                "gripper": 0,
            },  # approach meet position
            {
                "t": 340,
                "xyz": meet_xyz + np.array([0.05, 0, lift_right]),
                "quat": gripper_pick_quat_right.elements,
                "gripper": 0,
            },  # insertion
            {
                "t": 400,
                "xyz": meet_xyz + np.array([0.05, 0, lift_right]),
                "quat": gripper_pick_quat_right.elements,
                "gripper": 0,
            },  # insertion
        ]


def test_policy(task_name, policy_cls):
    # example rolling out pick_and_transfer policy
    onscreen_render = True
    inject_noise = False

    # setup the environment
    env = gym.make(task_name, obs_type="pixels_agent_pos")

    for episode_idx in range(2):
        observation, info = env.reset()
        # init episode with first observation and info
        episode = [[observation, info]]
        frames = [observation["pixels"]["top"]]
        if onscreen_render:
            ax = plt.subplot()
            plt_img = ax.imshow(observation["pixels"]["top"])
            plt.ion()

        policy = policy_cls(inject_noise)
        for _ in range(SIM_EPISODE_LENGTH):
            action = policy(observation)
            observation, reward, terminated, truncated, info = env.step(action)
            episode.append([observation, reward, terminated, truncated, info])
            frames.append(observation["pixels"]["top"])
            if onscreen_render:
                plt_img.set_data(observation["pixels"]["top"])
                plt.pause(0.02)
        plt.close()

        episode_return = np.sum([ep[1] for ep in episode[1:]])
        if episode_return > 0:
            print(f"{episode_idx=} Successful, {episode_return=}")
            imageio.mimsave(f"example_episode_{episode_idx}.mp4", np.stack(frames), fps=50)
        else:
            print(f"{episode_idx=} Failed")


if __name__ == "__main__":
    # test_policy("gym_so100/SO100EETransferCube-v0", PickAndTransferPolicy)
    test_policy("gym_so100/SO100EEInsertion-v0", InsertionPolicy)