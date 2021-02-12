#### Test
import time
import datetime
import pytest
import logging

from abstract_open_traffic_generator.result import FlowRequest
from abstract_open_traffic_generator.control import FlowTransmit

from tests.common.helpers.assertions import pytest_assert

from tests.common.fixtures.conn_graph_facts import conn_graph_facts,\
    fanout_graph_facts

from tests.common.ixia.ixia_fixtures import ixia_api_serv_ip, \
    ixia_api_serv_user, ixia_api_serv_passwd, ixia_dev, ixia_api_serv_port,\
    ixia_api_serv_session_id, api


from files.configs.pfc_wd import pfc_watch_dog_config, serializer, \
    pfc_watch_dog_multi_host_config, one_hundred_gbe
from files.configs.pfc_wd import start_delay, pause_line_rate,\
    traffic_line_rate, frame_size
from files.qos_fixtures import lossless_prio_dscp_map

logger = logging.getLogger(__name__)

START_DELAY = [1]
PAUSE_LINE_RATE = [50]
TRAFFIC_LINE_RATE = [50]
FRAME_SIZE = [1024]
T_START_PAUSE = [5]
T_STOP_PAUSE = [10]
T_STOP_TRAFFIC = [15]
STORM_DETECTION_TIME = [400]
STORM_RESTORATION_TIME = [2000]


@pytest.mark.parametrize('start_delay', START_DELAY)
@pytest.mark.parametrize('pause_line_rate', PAUSE_LINE_RATE)
@pytest.mark.parametrize('traffic_line_rate', TRAFFIC_LINE_RATE)
@pytest.mark.parametrize('frame_size', FRAME_SIZE)
@pytest.mark.parametrize('t_start_pause', T_START_PAUSE)
@pytest.mark.parametrize('t_stop_pause', T_STOP_PAUSE)
@pytest.mark.parametrize('t_stop_traffic', T_STOP_TRAFFIC)
@pytest.mark.parametrize('storm_detection_time', STORM_DETECTION_TIME)
@pytest.mark.parametrize('storm_restoration_time', STORM_RESTORATION_TIME)

def test_pfc_watch_dog(api, 
                        duthost, 
                        pfc_watch_dog_config, 
                        lossless_prio_dscp_map,
                        start_delay, 
                        traffic_line_rate,
                        pause_line_rate,
                        frame_size,
                        t_start_pause,
                        t_stop_pause,
                        t_stop_traffic,
                        storm_detection_time,
                        storm_restoration_time,
                        serializer) :
    """
    +-----------------+           +--------------+           +-----------------+       
    | Keysight Port 1 |------ et1 |   SONiC DUT  | et2 ------| Keysight Port 2 | 
    +-----------------+           +--------------+           +-----------------+ 
                                       et3
                                        |
                                        |
                                        |
                                +-----------------+
                                | Keysight Port 3 |
                                +-----------------+

    Configuration:
    1. Configure a single lossless priority value Pi (0 <= i <= 7).
    2. Enable watchdog with default storm detection time (400ms) and restoration time (2sec).
    3. On Keysight Chassis, create bi-directional traffic between Port 1 and Port 2
       with DSCP value mapped to lossless priority Pi
       a. Traffic 1->2
       b. Traffic 2->1
    4. Create bi-directional traffic between Port 2 and Port 3 with DSCP value mapped 
       to lossless priority Pi
       a. Traffic 2->3
       b. Traffic 3->2
    5. Create PFC pause storm: Persistent PFC pause frames from Keysight port 3 to et3 of DUT.
        Priority of the PFC pause frames should be same as that configured in DUT 
        and the inter-frame transmission interval should be lesser than per-frame pause duration.

    # Workflow
    1. At time TstartTraffic , start all the bi-directional lossless traffic items.
    2. At time TstartPause , start PFC pause storm.
    3. At time TstopPause , stop PFC pause storm. (TstopPause - TstartPause) should be larger than 
        PFC storm detection time to trigger PFC watchdog.
    4. At time TstopTraffic , stop lossless traffic items. Note that (TstopTraffic - TstopPause) should 
        be larger than PFC storm restoration time to re-enable PFC.
    5. Verify the following:
        --> PFC watchdog is triggered on the corresponding lossless priorities at DUT interface et3.
        --> 'Traffic 1->2' and 'Traffic 2->1' must not experience any packet loss in both directions. 
            Its throughput should be close to 50% of the line rate.
        --> For 'Traffic 2->3' and 'Traffic 3->2' , between TstartPause and TstopPause , 
            there should be almost 100% packet loss in both directions.
        --> After TstopPause , the traffic throughput should gradually increase and become 50% of line rate in both directions.
        --> There should not be any traffic loss after PFC storm restoration time has elapsed.
    """

    #######################################################################
    # DUT Configuration
    #######################################################################
    duthost.shell('sudo pfcwd stop')

    cmd = 'sudo pfcwd start --action drop ports all detection-time {} \
           --restoration-time {}'.format(storm_detection_time,storm_restoration_time)
    duthost.shell(cmd)

    duthost.shell('pfcwd show config')
    
    t_btwn_start_pause_and_stop_pause = t_stop_pause - t_start_pause
    t_btwn_stop_pause_and_stop_traffic = t_stop_traffic - t_stop_pause
    
    if storm_detection_time > (t_btwn_start_pause_and_stop_pause*1000):
        pytest_assert(False,
            "Storm Detection period should be less than time between Start Pause and Stop Pause")
        
    if  storm_restoration_time > (t_btwn_stop_pause_and_stop_traffic*1000):
        pytest_assert(False,
            "Storm Restoration period should be less than time between Stop Pause and Stop Traffic")
        

    #######################################################################
    # TGEN Config and , Repeating TEST for Lossless priority 3 and 4
    #######################################################################
    pi_list = [prio for prio in lossless_prio_dscp_map]
    for pi in pi_list:   
        config = pfc_watch_dog_config(start_delay,
                                        pause_line_rate,
                                        traffic_line_rate,
                                        frame_size,
                                        t_start_pause,
                                        pi)
        api.set_config(None)
        # print(serializer.json(config))
        api.set_config(config)
    
        ###############################################################################################
        # Start all flows 
        # 1. check for no loss in the flows Traffic 1->2,Traffic 2->1
        # 2. check for loss in 'Traffic 2->3','Traffic 3->2' during pause storm
        ###############################################################################################
        
        api.set_flow_transmit(FlowTransmit(state='start'))
        
        # Sleeping till t_start_pause as t_start_pause is added as start_delay to the flow 
        time.sleep(start_delay + t_start_pause)
        
        t_to_stop_pause  = datetime.datetime.now() + datetime.timedelta(seconds=t_btwn_start_pause_and_stop_pause)

        #Check for traffic observations for two timestamps in t_btwn_start_pause_and_stop_pause
        while True:
            if datetime.datetime.now() >= t_to_stop_pause:
                break
            else:
                time.sleep(t_btwn_start_pause_and_stop_pause/2)   
                # Get statistics
                test_stat = api.get_flow_results(FlowRequest())
                
                # Define indices
                tx_frame_rate_index = test_stat['columns'].index('frames_tx_rate')
                rx_frame_rate_index = test_stat['columns'].index('frames_rx_rate')
                name_index = test_stat['columns'].index('name')
                
                for rows in test_stat['rows'] :
                    if rows[name_index] in ['Traffic 1->2','Traffic 2->1'] :
                        tx_frame_rate = int(float(rows[tx_frame_rate_index]))
                        rx_frame_rate = int(float(rows[rx_frame_rate_index]))
                        logger.info("Tx Frame Rate,Rx Frame Rate of {} during Pause Storm: {},{}"
                                    .format(rows[name_index],tx_frame_rate,rx_frame_rate))  
                        if ((tx_frame_rate != rx_frame_rate) or (rx_frame_rate == 0)) :
                            pytest_assert(False,
                                        "Observing loss for %s during pause storm which is not expected" %(rows[name_index]))
                    elif rows[name_index] in ['Traffic 2->3','Traffic 3->2']:
                        tx_frame_rate = int(float(rows[tx_frame_rate_index]))
                        rx_frame_rate = int(float(rows[rx_frame_rate_index]))
                        logger.info("Tx Frame Rate,Rx Frame Rate of {} during Pause Storm: {},{}"
                                    .format(rows[name_index],tx_frame_rate,rx_frame_rate)) 
                        if ((tx_frame_rate == 0 ) or (rx_frame_rate == tx_frame_rate)) :
                            pytest_assert(False,
                                        "Expecting loss for %s during pause storm, which didn't occur" %(rows[name_index]))
                    
        ###############################################################################################
        # Stop Pause Storm
        # 1. check for no loss in the flows Traffic 1->2,Traffic 2->1
        # 2. check for no loss in 'Traffic 2->3','Traffic 3->2' after stopping Pause Storm
        ###############################################################################################
        # pause storm will stop once loop completes,the current time reaches t_stop_pause
        api.set_flow_transmit(FlowTransmit(state='stop',flow_names=['Pause Storm']))
        
        # Verification after pause storm is stopped
        t_to_stop_traffic  = datetime.datetime.now() + datetime.timedelta(seconds=t_btwn_stop_pause_and_stop_traffic)
        
        #Check for traffic observations for two timestamps in t_btwn_stop_pause_and_stop_traffic
        while True:
            if datetime.datetime.now() >= t_to_stop_traffic:
                break
            else:
                time.sleep(t_btwn_stop_pause_and_stop_traffic/2)
                # Get statistics
                test_stat = api.get_flow_results(FlowRequest())
                
                # Define indices
                tx_frame_rate_index = test_stat['columns'].index('frames_tx_rate')
                rx_frame_rate_index = test_stat['columns'].index('frames_rx_rate')
                name_index = test_stat['columns'].index('name')
                
                for rows in test_stat['rows'] :
                    if rows[name_index] in ['Traffic 1->2','Traffic 2->1'] :
                        tx_frame_rate = int(float(rows[tx_frame_rate_index]))
                        rx_frame_rate = int(float(rows[rx_frame_rate_index]))
                        logger.info("Tx Frame Rate,Rx Frame Rate of {} after stopping Pause Storm: {},{}"
                                    .format(rows[name_index],tx_frame_rate,rx_frame_rate))
                        if ((tx_frame_rate != rx_frame_rate) or (rx_frame_rate == 0)) :
                            pytest_assert(False,
                                        "Observing loss for %s after pause storm stopped which is not expected" %(rows[name_index]))
                    elif rows[name_index] in ['Traffic 2->3','Traffic 3->2']:
                        tx_frame_rate = int(float(rows[tx_frame_rate_index]))
                        rx_frame_rate = int(float(rows[rx_frame_rate_index]))
                        logger.info("Tx Frame Rate,Rx Frame Rate of {} after stopping Pause Storm: {},{}"
                                    .format(rows[name_index],tx_frame_rate,rx_frame_rate)) 
                        if ((tx_frame_rate != rx_frame_rate) or (rx_frame_rate == 0)) :
                            pytest_assert(False,
                                        "Observing loss for %s after pause storm stopped which is not expected" %(rows[name_index]))
         
        # stop all flows
        api.set_flow_transmit(FlowTransmit(state='stop'))


START_DELAY = [1]
PAUSE_LINE_RATE = [50]
TRAFFIC_LINE_RATE = [50]
FRAME_SIZE = [1024]
T_START_PAUSE = [5]
T_STOP_PAUSE = [10]
T_STOP_TRAFFIC = [15]
STORM_DETECTION_TIME = [400]
STORM_RESTORATION_TIME = [2000]


@pytest.mark.parametrize('start_delay', START_DELAY)
@pytest.mark.parametrize('pause_line_rate', PAUSE_LINE_RATE)
@pytest.mark.parametrize('traffic_line_rate', TRAFFIC_LINE_RATE)
@pytest.mark.parametrize('frame_size', FRAME_SIZE)
@pytest.mark.parametrize('t_start_pause', T_START_PAUSE)
@pytest.mark.parametrize('t_stop_pause', T_STOP_PAUSE)
@pytest.mark.parametrize('t_stop_traffic', T_STOP_TRAFFIC)
@pytest.mark.parametrize('storm_detection_time', STORM_DETECTION_TIME)
@pytest.mark.parametrize('storm_restoration_time', STORM_RESTORATION_TIME)

def test_multi_host_pfc_watch_dog(api, 
                                duthost, 
                                pfc_watch_dog_multi_host_config, 
                                lossless_prio_dscp_map,
                                start_delay, 
                                traffic_line_rate,
                                pause_line_rate,
                                frame_size,
                                t_start_pause,
                                t_stop_pause,
                                t_stop_traffic,
                                storm_detection_time,
                                storm_restoration_time,
                                serializer) :
    """
    +-----------------+           +--------------+           +-----------------+       
    | Keysight Port 1 |------ et1 |   SONiC DUT  | et2 ------| Keysight Port 2 | 
    +-----------------+           +--------------+           +-----------------+ 
                                       et3
                                        |
                                        |
                                        |
                                +-----------------+
                                | Keysight Port 3 |
                                +-----------------+

    Configuration:
    1. Configure a single lossless priority value Pi (0 <= i <= 7).
    2. Enable watchdog with default storm detection time (400ms) and restoration time (2sec).
    3. On Keysight Chassis, create bi-directional traffic between Port 1 and Port 2
       with DSCP value mapped to lossless priority Pi
       a. Traffic 1->2
       b. Traffic 2->1
    4. Create bi-directional traffic between Port 2 and Port 3 with DSCP value mapped 
       to lossless priority Pi
       a. Traffic 2->3
       b. Traffic 3->2
    5. Create bi-directional traffic between Port 2 and Port 3 with DSCP value mapped 
       to lossless priority Pi
       a. Traffic 3->1
       b. Traffic 1->3
    6. Create PFC pause storm: Persistent PFC pause frames from Keysight port 3 to et3 of DUT.
        Priority of the PFC pause frames should be same as that configured in DUT 
        and the inter-frame transmission interval should be lesser than per-frame pause duration.

    # Workflow
    1. At time TstartTraffic , start all the bi-directional lossless traffic items.
    2. At time TstartPause , start PFC pause storm.
    3. At time TstopPause , stop PFC pause storm. (TstopPause - TstartPause) should be larger than 
        PFC storm detection time to trigger PFC watchdog.
    4. At time TstopTraffic , stop lossless traffic items. Note that (TstopTraffic - TstopPause) should 
        be larger than PFC storm restoration time to re-enable PFC.
    5. Verify the following:
        --> PFC watchdog is triggered on the corresponding lossless priorities at DUT interface et3.
        --> 'Traffic 1->2' and 'Traffic 2->1' must not experience any packet loss in both directions. 
            Its throughput should be close to 50% of the line rate.
        --> For 'Traffic 2->3', 'Traffic 3->2', 'Traffic 1->3' and 'Traffic 3->1' between TstartPause and TstopPause , 
            there should be almost 100% packet loss in both directions.
        --> After TstopPause , the traffic throughput should gradually increase and become 50% of line rate in both directions.
        --> There should not be any traffic loss after PFC storm restoration time has elapsed.
    """

    #######################################################################
    # DUT Configuration
    #######################################################################
    duthost.shell('sudo pfcwd stop')

    cmd = 'sudo pfcwd start --action drop ports all detection-time {} \
           --restoration-time {}'.format(storm_detection_time,storm_restoration_time)
    duthost.shell(cmd)

    duthost.shell('pfcwd show config')
    
    t_btwn_start_pause_and_stop_pause = t_stop_pause - t_start_pause
    t_btwn_stop_pause_and_stop_traffic = t_stop_traffic - t_stop_pause
    
    if storm_detection_time > (t_btwn_start_pause_and_stop_pause*1000):
        pytest_assert(False,
            "Storm Detection period should be less than time between Start Pause and Stop Pause")
        
    if  storm_restoration_time > (t_btwn_stop_pause_and_stop_traffic*1000):
        pytest_assert(False,
            "Storm Restoration period should be less than time between Stop Pause and Stop Traffic")
        

    #######################################################################
    # TGEN Config and , Repeating TEST for Lossless priority 3 and 4
    #######################################################################
    pi_list = [prio for prio in lossless_prio_dscp_map]
    for pi in pi_list:
        config = pfc_watch_dog_multi_host_config(start_delay,
                                        pause_line_rate,
                                        traffic_line_rate,
                                        frame_size,
                                        t_start_pause,
                                        pi)
        api.set_config(None)
        # print(serializer.json(config))
        api.set_config(config)
    
        ###############################################################################################
        # Start all flows 
        # 1. check for no loss in the flows Traffic 1->2,Traffic 2->1
        # 2. check for loss in 'Traffic 2->3','Traffic 3->2','Traffic 1->3','Traffic 3->1' 
        #    during pause storm
        ###############################################################################################
        
        api.set_flow_transmit(FlowTransmit(state='start'))
        
        # Sleeping till t_start_pause as t_start_pause is added as start_delay to the flow 
        time.sleep(start_delay + t_start_pause)
        
        t_to_stop_pause  = datetime.datetime.now() + datetime.timedelta(seconds=t_btwn_start_pause_and_stop_pause)

        #Check for traffic observations for two timestamps in t_btwn_start_pause_and_stop_pause
        while True:
            if datetime.datetime.now() >= t_to_stop_pause:
                break
            else:
                time.sleep(t_btwn_start_pause_and_stop_pause/2)   
                # Get statistics
                test_stat = api.get_flow_results(FlowRequest())
                
                # Define indices
                tx_frame_rate_index = test_stat['columns'].index('frames_tx_rate')
                rx_frame_rate_index = test_stat['columns'].index('frames_rx_rate')
                name_index = test_stat['columns'].index('name')
                
                for rows in test_stat['rows'] :
                    if rows[name_index] in ['Traffic 1->2','Traffic 2->1'] :
                        tx_frame_rate = int(float(rows[tx_frame_rate_index]))
                        rx_frame_rate = int(float(rows[rx_frame_rate_index]))
                        logger.info("Tx Frame Rate,Rx Frame Rate of {} during Pause Storm: {},{}"
                                    .format(rows[name_index],tx_frame_rate,rx_frame_rate))  
                        if ((tx_frame_rate != rx_frame_rate) or (rx_frame_rate == 0)) :
                            pytest_assert(False,
                                        "Observing loss for %s during pause storm which is not expected" %(rows[name_index]))
                    elif rows[name_index] in ['Traffic 2->3','Traffic 3->2','Traffic 1->3','Traffic 3->1']:
                        tx_frame_rate = int(float(rows[tx_frame_rate_index]))
                        rx_frame_rate = int(float(rows[rx_frame_rate_index]))
                        logger.info("Tx Frame Rate,Rx Frame Rate of {} during Pause Storm: {},{}"
                                    .format(rows[name_index],tx_frame_rate,rx_frame_rate)) 
                        if ((tx_frame_rate == 0 ) or (rx_frame_rate == tx_frame_rate)) :
                            pytest_assert(False,
                                        "Expecting loss for %s during pause storm, which didn't occur" %(rows[name_index]))
                    
        ###############################################################################################
        # Stop Pause Storm
        # 1. check for no loss in the flows Traffic 1->2,Traffic 2->1
        # 2. check for no loss in 'Traffic 2->3','Traffic 3->2','Traffic 1->3','Traffic 3->1'
        #    after stopping Pause Storm
        ###############################################################################################
        # pause storm will stop once loop completes,the current time reaches t_stop_pause
        api.set_flow_transmit(FlowTransmit(state='stop',flow_names=['Pause Storm']))
        
        # Verification after pause storm is stopped
        t_to_stop_traffic  = datetime.datetime.now() + datetime.timedelta(seconds=t_btwn_stop_pause_and_stop_traffic)
        
        #Check for traffic observations for two timestamps in t_btwn_stop_pause_and_stop_traffic
        while True:
            if datetime.datetime.now() >= t_to_stop_traffic:
                break
            else:
                time.sleep(t_btwn_stop_pause_and_stop_traffic/2)
                # Get statistics
                test_stat = api.get_flow_results(FlowRequest())
                
                # Define indices
                tx_frame_rate_index = test_stat['columns'].index('frames_tx_rate')
                rx_frame_rate_index = test_stat['columns'].index('frames_rx_rate')
                name_index = test_stat['columns'].index('name')
                
                for rows in test_stat['rows'] :
                    if rows[name_index] in ['Traffic 1->2','Traffic 2->1'] :
                        tx_frame_rate = int(float(rows[tx_frame_rate_index]))
                        rx_frame_rate = int(float(rows[rx_frame_rate_index]))
                        logger.info("Tx Frame Rate,Rx Frame Rate of {} after stopping Pause Storm: {},{}"
                                    .format(rows[name_index],tx_frame_rate,rx_frame_rate))
                        if ((tx_frame_rate != rx_frame_rate) or (rx_frame_rate == 0)) :
                            pytest_assert(False,
                                        "Observing loss for %s after pause storm stopped which is not expected" %(rows[name_index]))
                    elif rows[name_index] in ['Traffic 2->3','Traffic 3->2','Traffic 1->3','Traffic 3->1']:
                        tx_frame_rate = int(float(rows[tx_frame_rate_index]))
                        rx_frame_rate = int(float(rows[rx_frame_rate_index]))
                        logger.info("Tx Frame Rate,Rx Frame Rate of {} after stopping Pause Storm: {},{}"
                                    .format(rows[name_index],tx_frame_rate,rx_frame_rate)) 
                        if ((tx_frame_rate != rx_frame_rate) or (rx_frame_rate == 0)) :
                            pytest_assert(False,
                                        "Observing loss for %s after pause storm stopped which is not expected" %(rows[name_index]))
         
        # stop all flows
        api.set_flow_transmit(FlowTransmit(state='stop'))