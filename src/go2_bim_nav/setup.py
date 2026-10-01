import os
from glob import glob

from setuptools import setup

package_name = 'go2_bim_nav'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'maps'), glob('maps/*')),
    ],
    install_requires=['setuptools', 'PyYAML'],
    zip_safe=True,
    maintainer='your_name',
    maintainer_email='you@example.com',
    description=(
        'BIM-grounded Nav2 stack for the Unitree Go2: IFC-derived static '
        'map plus lidar-based dynamic obstacle avoidance.'
    ),
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'ifc_to_map = go2_bim_nav.ifc_to_map:main',
            'send_goal = go2_bim_nav.send_goal:main',
            'list_spaces = go2_bim_nav.list_spaces:main',
            'cmd_vel_bridge = go2_bim_nav.cmd_vel_bridge:main',
            'odom_to_tf = go2_bim_nav.odom_to_tf:main',
        ],
    },
)
