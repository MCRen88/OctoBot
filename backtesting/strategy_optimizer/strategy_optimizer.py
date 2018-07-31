import logging
import copy
import math

from tools.class_inspector import get_class_from_string, evaluator_parent_inspection
from tests.test_utils.backtesting_util import add_config_default_backtesting_values
from tests.test_utils.config import load_test_config
from tools.data_util import DataUtil
from evaluator.TA.TA_evaluator import TAEvaluator
from evaluator import TA
from evaluator import Strategies
from evaluator.Strategies.strategies_evaluator import StrategiesEvaluator
from config.cst import CONFIG_TRADER_RISK, CONFIG_TRADER, CONFIG_FORCED_EVALUATOR, CONFIG_FORCED_TIME_FRAME, \
    CONFIG_EVALUATOR, CONFIG_TRADER_MODE
from backtesting.strategy_optimizer.strategy_test_suite import StrategyTestSuite
from tools.logging_util import set_global_logger_level

CONFIG = 0
RANK = 1
TRADES = 0
TRADES_IN_RESULT = 2


class StrategyOptimizer:

    def __init__(self, config, strategy_name):
        self.is_properly_initialized = False
        self.logger = logging.getLogger(self.get_name())
        self.config = load_test_config()
        self.trading_mode = config[CONFIG_TRADER][CONFIG_TRADER_MODE]
        self.config[CONFIG_TRADER][CONFIG_TRADER_MODE] = self.trading_mode
        self.config[CONFIG_EVALUATOR] = config[CONFIG_EVALUATOR]
        add_config_default_backtesting_values(self.config)
        self.strategy_class = get_class_from_string(strategy_name, StrategiesEvaluator,
                                                    Strategies, evaluator_parent_inspection)
        self.run_results = []
        self.results_report = []
        self.sorted_results_by_time_frame = {}
        self.sorted_results_through_all_time_frame = {}
        self.all_time_frames = []

        self.is_computing = False
        self.run_id = 0
        self.total_nb_runs = 0

        if not self.strategy_class:
            self.logger.error(f"Impossible to find a strategy matching class name: {strategy_name} in installed "
                              f"strategies. Please make sure to enter the name of the class, "
                              f"ex: FullMixedStrategiesEvaluator")
        else:
            self.is_properly_initialized = True

    def find_optimal_configuration(self, TAs=None, time_frames=None, risks=None):

        if not self.is_computing:

            # set is_computing to True to prevent any simultaneous start
            self.is_computing = True

            try:
                all_TAs = self.get_all_TA(self.config[CONFIG_EVALUATOR]) if TAs is None else TAs
                nb_TAs = len(all_TAs)

                self.all_time_frames = self.strategy_class.get_required_time_frames(self.config) \
                    if time_frames is None else time_frames
                nb_TFs = len(self.all_time_frames)

                risks = [0.5, 1] if risks is None else risks

                self.logger.info(f"Trying to find an optimized configuration for {self.strategy_class.get_name()} "
                                 f"strategy using {self.trading_mode} trading mode, {all_TAs} technical evaluator(s), "
                                 f"{self.all_time_frames} time frames and {risks} risk(s).")

                self.total_nb_runs = int(len(risks) * (math.pow(nb_TFs, 2) * math.pow(nb_TAs, 2)))

                set_global_logger_level(logging.ERROR)

                self.run_id = 1
                # test with several risks
                for risk in risks:
                    self.config[CONFIG_TRADER][CONFIG_TRADER_RISK] = risk
                    eval_conf_history = []
                    # test with several evaluators
                    for evaluator_conf_iteration in range(nb_TAs):
                        current_forced_evaluator = all_TAs[evaluator_conf_iteration]
                        # test with 1-n evaluators at a time
                        for nb_evaluators in range(1, nb_TAs+1):
                            # test different configurations
                            for i in range(nb_TAs):
                                activated_evaluators = self.get_activated_element(all_TAs, current_forced_evaluator,
                                                                                  nb_evaluators, eval_conf_history,
                                                                                  self.strategy_class.get_name(),
                                                                                  True)
                                if activated_evaluators is not None:
                                    self.config[CONFIG_FORCED_EVALUATOR] = activated_evaluators
                                    time_frames_conf_history = []
                                    # test different time frames
                                    for time_frame_conf_iteration in range(nb_TFs):
                                        current_forced_time_frame = self.all_time_frames[time_frame_conf_iteration]
                                        # test with 1-n time frames at a time
                                        for nb_time_frames in range(1, nb_TFs+1):
                                            # test different configurations
                                            for j in range(nb_TFs):
                                                activated_time_frames = \
                                                    self.get_activated_element(self.all_time_frames,
                                                                               current_forced_time_frame,
                                                                               nb_time_frames,
                                                                               time_frames_conf_history)
                                                if activated_time_frames is not None:
                                                    self.config[CONFIG_FORCED_TIME_FRAME] = activated_time_frames
                                                    print(f"{self.run_id}/{self.total_nb_runs} Run with: evaluators: "
                                                          f"{activated_evaluators}, "
                                                          f"time frames :{activated_time_frames}, risk: {risk}")
                                                    self._run_test_suite(self.config)
                                                    print(f" => Result: "
                                                          f"{self.run_results[-1].get_result_string(False)}")
                                                    self.run_id += 1

                self._find_optimal_configuration_using_results()

            finally:
                set_global_logger_level(logging.INFO)
                self.is_computing = False
                self.logger.info(f"{self.get_name()} finished computation.")
        else:
            raise RuntimeError(f"{self.get_name()} is already computing: processed "
                               f"{self.run_id}/{self.total_nb_runs} processed")

    def _run_test_suite(self, config):
        strategy_test_suite = StrategyTestSuite()
        strategy_test_suite.init(self.strategy_class, copy.deepcopy(config))
        strategy_test_suite.run_test_suite(strategy_test_suite)
        run_result = strategy_test_suite.get_test_suite_result()
        self.run_results.append(run_result)

    def _find_optimal_configuration_using_results(self):
        for time_frame in self.all_time_frames:
            time_frame_sorted_results = self.get_sorted_results(self.run_results, time_frame)
            self.sorted_results_by_time_frame[time_frame.value] = time_frame_sorted_results

        results_through_all_time_frame = {}
        for results in self.sorted_results_by_time_frame.values():
            for rank, result in enumerate(results):
                result_summary = result.get_config_summary()
                if result_summary not in results_through_all_time_frame:
                    results_through_all_time_frame[result_summary] = [[], 0]
                results_through_all_time_frame[result_summary][RANK] += rank
                results_through_all_time_frame[result_summary][TRADES] += result.trades_counts

        result_list = [(result, trades_and_rank[RANK], DataUtil.mean(trades_and_rank[TRADES]))
                       for result, trades_and_rank in results_through_all_time_frame.items()]
        self.sorted_results_through_all_time_frame = sorted(result_list, key=lambda res: res[RANK])

    def print_report(self):
        self.logger.info("Full execution sorted results: Minimum time frames are defining the range of the run "
                         "since it finishes at the end of the first data, aka minimum time frame. Therefore all "
                         "different time frames are different price actions and can't be compared independently.")
        for time_frame, results in self.sorted_results_by_time_frame.items():
            self.logger.info(f" *** {time_frame} minimum time frame ranking*** ")
            for rank, result in enumerate(results):
                self.logger.info(f"{rank}: {result.get_result_string()}")
        self.logger.info(f" *** Top rankings per time frame *** ")
        for time_frame, results in self.sorted_results_by_time_frame.items():
            for i in range(0, min(len(results), 5)):
                self.logger.info(f"{time_frame}: {results[i].get_result_string(False)}")
        self.logger.info(f" *** Top rankings through all time frames *** ")
        for rank, result in enumerate(self.sorted_results_through_all_time_frame[0:25]):
            self.logger.info(f"{rank}: {result[CONFIG].get_result_string()} (time frame rank sum: {result[RANK]}) "
                             f"average trades count: {result[TRADES_IN_RESULT]:f}")
        self.logger.info(f" *** Overall best configuration for {self.strategy_class.get_name()} using "
                         f"{self.trading_mode} trading mode *** ")
        self.logger.info(f"{self.sorted_results_through_all_time_frame[0][CONFIG].get_result_string()} average "
                         f"trades count: {result[TRADES_IN_RESULT]:f}")

    def get_results(self):
        return self.run_results

    def get_current_progress(self):
        return self.run_id, self.total_nb_runs

    def get_is_computing(self):
        return self.is_computing

    @classmethod
    def get_name(cls):
        return cls.__name__

    @staticmethod
    def get_activated_element(all_elements, current_forced_element, nb_elements_to_consider,
                              elem_conf_history, default_element=None, dict_shaped=False):
        eval_conf = {current_forced_element: True}
        additional_elements_count = 0
        if default_element is not None:
            eval_conf[default_element] = True
            additional_elements_count = 1
        if nb_elements_to_consider > 1:
            i = 0
            while i < len(all_elements) and \
                    len(eval_conf) < nb_elements_to_consider+additional_elements_count:
                current_elem = all_elements[i]
                if current_elem not in eval_conf:
                    eval_conf[current_elem] = True
                    if len(eval_conf) == nb_elements_to_consider+additional_elements_count and \
                            ((eval_conf if dict_shaped else sorted([key.value for key in eval_conf]))
                             in elem_conf_history):
                        eval_conf.pop(current_elem)
                i += 1
        if len(eval_conf) == nb_elements_to_consider+additional_elements_count:
            to_use_conf = eval_conf
            if not dict_shaped:
                to_use_conf = sorted([key.value for key in eval_conf])
            if to_use_conf not in elem_conf_history:
                elem_conf_history.append(to_use_conf)
                return to_use_conf
        return None

    @staticmethod
    def get_filtered_results(results, time_frame=None):
        return [result for result in results if time_frame is None or result.min_time_frame == time_frame]

    @staticmethod
    def get_sorted_results(results, time_frame=None):
        return sorted(StrategyOptimizer.get_filtered_results(results, time_frame),
                      key=lambda result: result.get_average_score(), reverse=True)

    @staticmethod
    def _is_relevant_evaluation_config(evaluator):
        return get_class_from_string(evaluator, TAEvaluator, TA, evaluator_parent_inspection) is not None

    @staticmethod
    def get_all_TA(config_evaluator):
        return [evaluator
                for evaluator, activated in config_evaluator.items()
                if activated and StrategyOptimizer._is_relevant_evaluation_config(evaluator)]
