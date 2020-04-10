# Copyright (c) 2019-2020, NVIDIA CORPORATION. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#  * Neither the name of NVIDIA CORPORATION nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
# OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import sys
sys.path.append("../common")

from builtins import range
from future.utils import iteritems
import unittest
import time
import threading
import traceback
import numpy as np
import infer_util as iu
import test_util as tu
import sequence_util as su

from tensorrtserver.api import *
import os

TEST_SYSTEM_SHARED_MEMORY = bool(
    int(os.environ.get('TEST_SYSTEM_SHARED_MEMORY', 0)))
TEST_CUDA_SHARED_MEMORY = bool(int(os.environ.get('TEST_CUDA_SHARED_MEMORY',
                                                  0)))

_model_instances = 1
_max_queue_delay_ms = 10000
_max_sequence_idle_ms = 5000

_deferred_exceptions_lock = threading.Lock()
_deferred_exceptions = []


class InferShapeTensorTest(unittest.TestCase):

    def setUp(self):
        global _deferred_exceptions
        _deferred_exceptions = []

    def add_deferred_exception(self, ex):
        global _deferred_exceptions
        with _deferred_exceptions_lock:
            _deferred_exceptions.append(ex)

    def check_deferred_exception(self):
        # Just raise one of the exceptions...
        with _deferred_exceptions_lock:
            if len(_deferred_exceptions) > 0:
                raise _deferred_exceptions[0]

    def check_response(self,
                       bs,
                       thresholds,
                       shape_values,
                       dummy_input_shapes,
                       shm_region_names=None,
                       precreated_shm_regions=None,
                       shm_suffix=""):
        try:
            start_ms = int(round(time.time() * 1000))

            iu.infer_shape_tensor(
                self,
                'plan',
                bs,
                np.float32,
                shape_values,
                dummy_input_shapes,
                use_grpc=False,
                use_streaming=False,
                shm_suffix=shm_suffix,
                use_system_shared_memory=TEST_SYSTEM_SHARED_MEMORY,
                use_cuda_shared_memory=TEST_CUDA_SHARED_MEMORY)

            end_ms = int(round(time.time() * 1000))

            lt_ms = thresholds[0]
            gt_ms = thresholds[1]
            if lt_ms is not None:
                self.assertTrue(
                    (end_ms - start_ms) < lt_ms,
                    "expected less than " + str(lt_ms) +
                    "ms response time, got " + str(end_ms - start_ms) + " ms")
            if gt_ms is not None:
                self.assertTrue(
                    (end_ms - start_ms) > gt_ms,
                    "expected greater than " + str(gt_ms) +
                    "ms response time, got " + str(end_ms - start_ms) + " ms")
        except Exception as ex:
            self.add_deferred_exception(ex)

    def check_setup(self, url, protocol, model_name):
        # Make sure test.sh set up the correct batcher settings
        ctx = ServerStatusContext(url, protocol, model_name, True)
        ss = ctx.get_server_status()
        self.assertEqual(len(ss.model_status), 1)
        self.assertTrue(model_name in ss.model_status,
                        "expected status for model " + model_name)
        bconfig = ss.model_status[model_name].config.dynamic_batching
        self.assertTrue(2 in bconfig.preferred_batch_size)
        self.assertTrue(6 in bconfig.preferred_batch_size)
        self.assertEqual(bconfig.max_queue_delay_microseconds,
                         _max_queue_delay_ms * 1000)  # 10 secs

    def check_status(self, url, protocol, model_name, static_bs, exec_cnt,
                     infer_cnt):
        ctx = ServerStatusContext(url, protocol, model_name, True)
        ss = ctx.get_server_status()
        self.assertEqual(len(ss.model_status), 1)
        self.assertTrue(model_name in ss.model_status,
                        "expected status for model " + model_name)
        vs = ss.model_status[model_name].version_status
        self.assertEqual(len(vs), 1)
        self.assertTrue(1 in vs, "expected status for version 1")
        infer = vs[1].infer_stats
        self.assertEqual(
            len(infer), len(static_bs), "expected batch-sizes (" +
            ",".join(str(b) for b in static_bs) + "), got " + str(vs[1]))
        for b in static_bs:
            self.assertTrue(
                b in infer,
                "expected batch-size " + str(b) + ", got " + str(vs[1]))
        self.assertEqual(
            vs[1].model_execution_count, exec_cnt,
            "expected model-execution-count " + str(exec_cnt) + ", got " +
            str(vs[1].model_execution_count))
        self.assertEqual(
            vs[1].model_inference_count, infer_cnt,
            "expected model-inference-count " + str(infer_cnt) + ", got " +
            str(vs[1].model_inference_count))

    def test_static_batch(self):
        iu.infer_shape_tensor(
            self,
            'plan',
            8,
            np.float32, [[32, 32]], [[4, 4]],
            use_system_shared_memory=TEST_SYSTEM_SHARED_MEMORY,
            use_cuda_shared_memory=TEST_CUDA_SHARED_MEMORY)
        iu.infer_shape_tensor(
            self,
            'plan',
            8,
            np.float32, [[4, 4]], [[32, 32]],
            use_system_shared_memory=TEST_SYSTEM_SHARED_MEMORY,
            use_cuda_shared_memory=TEST_CUDA_SHARED_MEMORY)
        iu.infer_shape_tensor(
            self,
            'plan',
            8,
            np.float32, [[4, 4]], [[4, 4]],
            use_system_shared_memory=TEST_SYSTEM_SHARED_MEMORY,
            use_cuda_shared_memory=TEST_CUDA_SHARED_MEMORY)

    def test_nobatch(self):
        iu.infer_shape_tensor(
            self,
            'plan_nobatch',
            1,
            np.float32, [[32, 32]], [[4, 4]],
            use_system_shared_memory=TEST_SYSTEM_SHARED_MEMORY,
            use_cuda_shared_memory=TEST_CUDA_SHARED_MEMORY)
        iu.infer_shape_tensor(
            self,
            'plan_nobatch',
            1,
            np.float32, [[4, 4]], [[32, 32]],
            use_system_shared_memory=TEST_SYSTEM_SHARED_MEMORY,
            use_cuda_shared_memory=TEST_CUDA_SHARED_MEMORY)
        iu.infer_shape_tensor(
            self,
            'plan_nobatch',
            1,
            np.float32, [[4, 4]], [[4, 4]],
            use_system_shared_memory=TEST_SYSTEM_SHARED_MEMORY,
            use_cuda_shared_memory=TEST_CUDA_SHARED_MEMORY)

    def test_wrong_shape_values(self):
        over_shape_values = [[32, 33]]
        try:
            iu.infer_shape_tensor(
                self,
                'plan',
                8,
                np.float32,
                over_shape_values, [[4, 4]],
                use_system_shared_memory=TEST_SYSTEM_SHARED_MEMORY,
                use_cuda_shared_memory=TEST_CUDA_SHARED_MEMORY)
        except InferenceServerException as ex:
            self.assertEqual("inference:0", ex.server_id())
            self.assertTrue(
                "The shape value at index 2 is expected to be in range from 1 to 32, Got: 33"
                in ex.message())

    # Dynamic Batcher tests
    def test_dynamic_different_shape_values(self):
        # Send two requests with sum of static batch sizes ==
        # preferred size, but with different shape values. This
        # should cause the requests to not be batched. The first
        # response will come back immediately and the second
        # delayed by the max batch queue delay
        try:
            url = "localhost:8000"
            protocol = ProtocolType.HTTP
            model_name = tu.get_zero_model_name("plan", 1, np.float32)
            self.check_setup(url, protocol, model_name)
            self.assertFalse("TRTSERVER_DELAY_SCHEDULER" in os.environ)

            threads = []
            threads.append(
                threading.Thread(target=self.check_response,
                                 args=(3, (6000, None)),
                                 kwargs={
                                     'shape_values': [[2, 2]],
                                     'dummy_input_shapes': [[16, 16]],
                                     'shm_suffix': '{}'.format(len(threads))
                                 }))
            threads.append(
                threading.Thread(target=self.check_response,
                                 args=(3, (_max_queue_delay_ms * 1.5,
                                           _max_queue_delay_ms)),
                                 kwargs={
                                     'shape_values': [[4, 4]],
                                     'dummy_input_shapes': [[16, 16]],
                                     'shm_suffix': '{}'.format(len(threads))
                                 }))
            threads[0].start()
            time.sleep(1)
            threads[1].start()
            for t in threads:
                t.join()
            self.check_deferred_exception()
            self.check_status(url, protocol, model_name, (3,), 2, 6)
        except InferenceServerException as ex:
            self.assertTrue(False, "unexpected error {}".format(ex))

    def test_dynamic_identical_shape_values(self):
        # Send two requests with sum of static batch sizes ==
        # preferred size, but with identical shape values. This
        # should cause the requests to get batched. Both
        # responses should come back immediately.
        try:
            url = "localhost:8000"
            protocol = ProtocolType.HTTP
            model_name = tu.get_zero_model_name("plan", 1, np.float32)
            self.check_setup(url, protocol, model_name)
            self.assertFalse("TRTSERVER_DELAY_SCHEDULER" in os.environ)

            threads = []
            threads.append(
                threading.Thread(target=self.check_response,
                                 args=(4, (6000, None)),
                                 kwargs={
                                     'shape_values': [[4, 4]],
                                     'dummy_input_shapes': [[16, 16]],
                                     'shm_suffix': '{}'.format(len(threads))
                                 }))
            threads.append(
                threading.Thread(target=self.check_response,
                                 args=(2, (6000, None)),
                                 kwargs={
                                     'shape_values': [[4, 4]],
                                     'dummy_input_shapes': [[16, 16]],
                                     'shm_suffix': '{}'.format(len(threads))
                                 }))
            threads[0].start()
            time.sleep(1)
            threads[1].start()
            for t in threads:
                t.join()
            self.check_deferred_exception()
            self.check_status(url, protocol, model_name, (4, 2), 1, 6)
        except InferenceServerException as ex:
            self.assertTrue(False, "unexpected error {}".format(ex))


class SequenceBatcherShapeTensorTest(su.SequenceBatcherTestUtil):

    def get_expected_result(self, expected_result, value, flag_str=None):
        # Adjust the expected_result for models
        expected_result = value
        if (flag_str is not None) and ("start" in flag_str):
            expected_result += 1
        return expected_result

    def test_sequence_identical_shape_values(self):
        # Test model instances together are configured with
        # total-batch-size 4. Send four equal-length sequences
        # with identical shape values in parallel and make sure
        # they get completely batched into batch-size 4
        # inferences.
        self.clear_deferred_exceptions()
        dtype = np.float32
        try:
            model_name = tu.get_sequence_model_name("plan", dtype)
            protocol = "streaming"

            self.check_setup(model_name)

            # Need scheduler to wait for queue to contain all
            # inferences for both sequences.
            self.assertTrue("TRTSERVER_DELAY_SCHEDULER" in os.environ)
            self.assertEqual(int(os.environ["TRTSERVER_DELAY_SCHEDULER"]), 12)
            self.assertTrue("TRTSERVER_BACKLOG_DELAY_SCHEDULER" in os.environ)
            self.assertEqual(
                int(os.environ["TRTSERVER_BACKLOG_DELAY_SCHEDULER"]), 0)
            precreated_shm0_handles = self.precreate_register_shape_tensor_regions(
                ((2, 1), (4, 2), (8, 3)), dtype, 0)
            precreated_shm1_handles = self.precreate_register_shape_tensor_regions(
                ((2, 11), (4, 12), (8, 13)), dtype, 1)
            precreated_shm2_handles = self.precreate_register_shape_tensor_regions(
                ((2, 111), (4, 112), (8, 113)), dtype, 2)
            precreated_shm3_handles = self.precreate_register_shape_tensor_regions(
                ((2, 1111), (4, 1112), (8, 1113)), dtype, 3)
            threads = []
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        1001,
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 2, 1, None), (None, 4, 2, None), ("end", 8,
                                                                     3, None)),
                        self.get_expected_result(6, 3, "end"),
                        protocol,
                        precreated_shm0_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}".format(self._testMethodName, protocol)
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        1002,
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 2, 11, None), (None, 4, 12, None),
                         ("end", 8, 13, None)),
                        self.get_expected_result(36, 13, "end"),
                        protocol,
                        precreated_shm1_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}".format(self._testMethodName, protocol)
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        1003,
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 2, 111, None), (None, 4, 112, None),
                         ("end", 8, 113, None)),
                        self.get_expected_result(336, 113, "end"),
                        protocol,
                        precreated_shm2_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}".format(self._testMethodName, protocol)
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        1004,
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 2, 1111, None), (None, 4, 1112, None),
                         ("end", 8, 1113, None)),
                        self.get_expected_result(3336, 1113, "end"),
                        protocol,
                        precreated_shm3_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}".format(self._testMethodName, protocol)
                    }))

            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.check_deferred_exception()
            self.check_status(model_name, (1,), 3 * _model_instances, 12)
        except InferenceServerException as ex:
            self.assertTrue(False, "unexpected error {}".format(ex))
        finally:
            if TEST_SYSTEM_SHARED_MEMORY or TEST_CUDA_SHARED_MEMORY:
                self.cleanup_shm_regions(precreated_shm0_handles)
                self.cleanup_shm_regions(precreated_shm1_handles)
                self.cleanup_shm_regions(precreated_shm2_handles)
                self.cleanup_shm_regions(precreated_shm3_handles)

    def test_sequence_different_shape_values(self):
        # Test model instances together are configured with
        # total-batch-size 4. Send four equal-length sequences with
        # different shape values in 2 sequences and 2 sequences that
        # share the same shape value. Make sure that the 2 sequences
        # with same shapes batch together but other two sequences do
        # not.
        self.clear_deferred_exceptions()
        dtype = np.float32

        precreated_shm0_handles = self.precreate_register_shape_tensor_regions(
            ((1, 1), (1, 2), (1, 3)), dtype, 0)
        precreated_shm1_handles = self.precreate_register_shape_tensor_regions(
            ((32, 11), (32, 12), (32, 13)), dtype, 1)
        precreated_shm2_handles = self.precreate_register_shape_tensor_regions(
            ((16, 111), (16, 112), (16, 113)), dtype, 2)
        precreated_shm3_handles = self.precreate_register_shape_tensor_regions(
            ((1, 1111), (1, 1112), (1, 1113)), dtype, 3)
        try:
            model_name = tu.get_sequence_model_name("plan", dtype)
            protocol = "streaming"

            self.check_setup(model_name)

            # Need scheduler to wait for queue to contain all
            # inferences for both sequences.
            self.assertTrue("TRTSERVER_DELAY_SCHEDULER" in os.environ)
            self.assertEqual(int(os.environ["TRTSERVER_DELAY_SCHEDULER"]), 12)
            self.assertTrue("TRTSERVER_BACKLOG_DELAY_SCHEDULER" in os.environ)
            self.assertEqual(
                int(os.environ["TRTSERVER_BACKLOG_DELAY_SCHEDULER"]), 0)

            threads = []
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        1001,
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 1, 1, None), (None, 1, 2, None), ("end", 1,
                                                                     3, None)),
                        self.get_expected_result(6, 3, "end"),
                        protocol,
                        precreated_shm0_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}".format(self._testMethodName, protocol)
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        1002,
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 32, 11, None), (None, 32, 12, None),
                         ("end", 32, 13, None)),
                        self.get_expected_result(36, 13, "end"),
                        protocol,
                        precreated_shm1_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}".format(self._testMethodName, protocol)
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        1003,
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 16, 111, None), (None, 16, 112, None),
                         ("end", 16, 113, None)),
                        self.get_expected_result(336, 113, "end"),
                        protocol,
                        precreated_shm2_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}".format(self._testMethodName, protocol)
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        1004,
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 1, 1111, None), (None, 1, 1112, None),
                         ("end", 1, 1113, None)),
                        self.get_expected_result(3336, 1113, "end"),
                        protocol,
                        precreated_shm3_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}".format(self._testMethodName, protocol)
                    }))

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.check_deferred_exception()
            self.check_status(model_name, (1,), 9, 12)
        except InferenceServerException as ex:
            self.assertTrue(False, "unexpected error {}".format(ex))
        finally:
            if TEST_SYSTEM_SHARED_MEMORY or TEST_CUDA_SHARED_MEMORY:
                self.cleanup_shm_regions(precreated_shm0_handles)
                self.cleanup_shm_regions(precreated_shm1_handles)
                self.cleanup_shm_regions(precreated_shm2_handles)
                self.cleanup_shm_regions(precreated_shm3_handles)


class DynaSequenceBatcherTest(su.SequenceBatcherTestUtil):

    def get_expected_result(self, expected_result, corrid, value,
                            flag_str=None):
        expected_result = value
        if flag_str is not None:
            if "start" in flag_str:
                expected_result += 1
            if "end" in flag_str:
                expected_result += corrid
        return expected_result

    def _multi_sequence_different_shape_impl(self, sleep_secs):
        self.clear_deferred_exceptions()
        dtype = np.float32

        precreated_shm0_handles = self.precreate_register_dynaseq_shape_tensor_regions(
            ((1, 1), (12, 2), (2, 3)), dtype, 0)
        precreated_shm1_handles = self.precreate_register_dynaseq_shape_tensor_regions(
            ((3, 11), (4, 12), (5, 13)), dtype, 1)
        precreated_shm2_handles = self.precreate_register_dynaseq_shape_tensor_regions(
            ((6, 111), (7, 112), (8, 113)), dtype, 2)
        precreated_shm3_handles = self.precreate_register_dynaseq_shape_tensor_regions(
            ((9, 1111), (10, 1112), (11, 1113)), dtype, 3)

        try:
            model_name = tu.get_dyna_sequence_model_name("plan", dtype)
            protocol = "streaming"

            self.check_setup(model_name)
            self.assertFalse("TRTSERVER_DELAY_SCHEDULER" in os.environ)
            self.assertFalse("TRTSERVER_BACKLOG_DELAY_SCHEDULER" in os.environ)

            corrids = [1001, 1002, 1003, 1004]
            threads = []
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        corrids[0],
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 1, 1, None), (None, 12, 2, None), ("end", 2,
                                                                      3, None)),
                        self.get_expected_result(4 + corrids[0], corrids[0], 3,
                                                 "end"),
                        protocol,
                        precreated_shm0_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}_{}".format(self._testMethodName, protocol,
                                              corrids[0]),
                        'using_dynamic_batcher':
                            True
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        corrids[1],
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 3, 11, None), (None, 4, 12, None),
                         ("end", 5, 13, None)),
                        self.get_expected_result(36 + corrids[1], corrids[1],
                                                 13, "end"),
                        protocol,
                        precreated_shm1_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}_{}".format(self._testMethodName, protocol,
                                              corrids[1]),
                        'using_dynamic_batcher':
                            True
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        corrids[2],
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 6, 111, None), (None, 7, 112, None),
                         ("end", 8, 113, None)),
                        self.get_expected_result(336 + corrids[2], corrids[2],
                                                 113, "end"),
                        protocol,
                        precreated_shm2_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}_{}".format(self._testMethodName, protocol,
                                              corrids[2]),
                        'using_dynamic_batcher':
                            True
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        corrids[3],
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 9, 1111, None), (None, 10, 1112, None),
                         ("end", 11, 1113, None)),
                        self.get_expected_result(3336 + corrids[3], corrids[3],
                                                 1113, "end"),
                        protocol,
                        precreated_shm3_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}_{}".format(self._testMethodName, protocol,
                                              corrids[3]),
                        'using_dynamic_batcher':
                            True
                    }))

            for t in threads:
                t.start()
                if sleep_secs > 0:
                    time.sleep(sleep_secs)
            for t in threads:
                t.join()
            self.check_deferred_exception()
            self.check_status(model_name, (1,), 12, 12)
        except InferenceServerException as ex:
            self.assertTrue(False, "unexpected error {}".format(ex))
        finally:
            if TEST_SYSTEM_SHARED_MEMORY or TEST_CUDA_SHARED_MEMORY:
                self.cleanup_shm_regions(precreated_shm0_handles)
                self.cleanup_shm_regions(precreated_shm1_handles)
                self.cleanup_shm_regions(precreated_shm2_handles)
                self.cleanup_shm_regions(precreated_shm3_handles)

    def _multi_sequence_identical_shape_impl(self, sleep_secs):
        self.clear_deferred_exceptions()
        dtype = np.float32

        precreated_shm0_handles = self.precreate_register_dynaseq_shape_tensor_regions(
            ((2, 1), (4, 2), (8, 3)), dtype, 0)
        precreated_shm1_handles = self.precreate_register_dynaseq_shape_tensor_regions(
            ((2, 11), (4, 12), (8, 13)), dtype, 1)
        precreated_shm2_handles = self.precreate_register_dynaseq_shape_tensor_regions(
            ((2, 111), (4, 112), (8, 113)), dtype, 2)
        precreated_shm3_handles = self.precreate_register_dynaseq_shape_tensor_regions(
            ((2, 1111), (4, 1112), (8, 1113)), dtype, 3)

        try:
            model_name = tu.get_dyna_sequence_model_name("plan", dtype)
            protocol = "streaming"

            self.check_setup(model_name)
            self.assertFalse("TRTSERVER_DELAY_SCHEDULER" in os.environ)
            self.assertFalse("TRTSERVER_BACKLOG_DELAY_SCHEDULER" in os.environ)

            corrids = [1001, 1002, 1003, 1004]
            threads = []
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        corrids[0],
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 2, 1, None), (None, 4, 2, None), ("end", 8,
                                                                     3, None)),
                        self.get_expected_result(4 + corrids[0], corrids[0], 3,
                                                 "end"),
                        protocol,
                        precreated_shm0_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}_{}".format(self._testMethodName, protocol,
                                              corrids[0]),
                        'using_dynamic_batcher':
                            True
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        corrids[1],
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 2, 11, None), (None, 4, 12, None),
                         ("end", 8, 13, None)),
                        self.get_expected_result(36 + corrids[1], corrids[1],
                                                 13, "end"),
                        protocol,
                        precreated_shm1_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}_{}".format(self._testMethodName, protocol,
                                              corrids[1]),
                        'using_dynamic_batcher':
                            True
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        corrids[2],
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 2, 111, None), (None, 4, 112, None),
                         ("end", 8, 113, None)),
                        self.get_expected_result(336 + corrids[2], corrids[2],
                                                 113, "end"),
                        protocol,
                        precreated_shm2_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}_{}".format(self._testMethodName, protocol,
                                              corrids[2]),
                        'using_dynamic_batcher':
                            True
                    }))
            threads.append(
                threading.Thread(
                    target=self.check_sequence_shape_tensor_io,
                    args=(
                        model_name,
                        dtype,
                        corrids[3],
                        (None, None),
                        # (flag_str, shape_value, value, pre_delay_ms)
                        (("start", 2, 1111, None), (None, 4, 1112, None),
                         ("end", 8, 1113, None)),
                        self.get_expected_result(3336 + corrids[3], corrids[3],
                                                 1113, "end"),
                        protocol,
                        precreated_shm3_handles),
                    kwargs={
                        'sequence_name':
                            "{}_{}_{}".format(self._testMethodName, protocol,
                                              corrids[3]),
                        'using_dynamic_batcher':
                            True
                    }))

            for t in threads:
                t.start()
                if sleep_secs > 0:
                    time.sleep(sleep_secs)
            for t in threads:
                t.join()
            self.check_deferred_exception()
            self.check_status(model_name, (1,), 3, 12)
        except InferenceServerException as ex:
            self.assertTrue(False, "unexpected error {}".format(ex))
        finally:
            if TEST_SYSTEM_SHARED_MEMORY or TEST_CUDA_SHARED_MEMORY:
                self.cleanup_shm_regions(precreated_shm0_handles)
                self.cleanup_shm_regions(precreated_shm1_handles)
                self.cleanup_shm_regions(precreated_shm2_handles)
                self.cleanup_shm_regions(precreated_shm3_handles)

    def test_dynaseq_identical_shape_values_series(self):
        # Send four sequences with identical shape values in series
        # and make sure they get completely batched into batch-size
        # 4 inferences.
        self._multi_sequence_identical_shape_impl(1)

    def test_dynaseq_identical_shape_values_parallel(self):
        # Send four sequences with identical shape values in parallel
        # and make sure they get completely batched into batch-size
        # 4 inferences.
        self._multi_sequence_identical_shape_impl(0)

    def test_dynaseq_different_shape_values_series(self):
        # Send four sequences with different shape values in series
        # and make sure they don't get batched together.
        self._multi_sequence_different_shape_impl(1)

    def test_dynaseq_different_shape_values_parallel(self):
        # Send four sequences with different shape values in parallel
        # and make sure they don't get batched together.
        self._multi_sequence_different_shape_impl(0)


if __name__ == '__main__':
    unittest.main()