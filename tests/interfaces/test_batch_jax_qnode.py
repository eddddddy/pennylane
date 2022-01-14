# Copyright 2018-2022 Xanadu Quantum Technologies Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Integration tests for using the jax interface with a QNode"""
import pytest
from pennylane import numpy as np

import pennylane as qml
from pennylane import qnode, QNode
from pennylane.tape import JacobianTape

qubit_device_and_diff_method = [
    ["default.qubit", "finite-diff", "backward"],
    ["default.qubit", "parameter-shift", "backward"],
    ["default.qubit", "backprop", "forward"],
    ["default.qubit", "adjoint", "forward"],
    ["default.qubit", "adjoint", "backward"],
]

jax = pytest.importorskip("jax")
jnp = jax.numpy


from jax.config import config

config.update("jax_enable_x64", True)


@pytest.mark.parametrize("dev_name,diff_method,mode", qubit_device_and_diff_method)
@pytest.mark.parametrize("jac_support", [None, True])
class TestQNode:
    """Test that using the QNode with JAX integrates with the PennyLane stack"""

    def test_execution_with_interface(self, dev_name, diff_method, mode, jac_support):
        """Test execution works with the interface"""
        if diff_method == "backprop":
            pytest.skip("Test does not support backprop")

        dev = qml.device(dev_name, wires=1)

        @qnode(dev, interface="jax", jac_support=jac_support, diff_method=diff_method)
        def circuit(a):
            qml.RY(a, wires=0)
            qml.RX(0.2, wires=0)
            return qml.expval(qml.PauliZ(0))

        a = np.array(0.1, requires_grad=True)
        circuit(a)

        assert circuit.interface == "jax"

        # the tape is able to deduce trainable parameters
        assert circuit.qtape.trainable_params == [0]

        # gradients should work
        grad = jax.grad(circuit)(a)
        assert isinstance(grad, jnp.DeviceArray)
        assert grad.shape == tuple()

    def test_jacobian(self, dev_name, diff_method, mode, mocker, tol, jac_support):
        """Test jacobian calculation"""
        if diff_method != "backprop" and not jac_support:
            pytest.skip(
                "JAX interface requires either the backprop device or jacobian support to be turned on."
            )

        if diff_method != "backprop" and mode == "forward":
            pytest.skip(
                "Computing the jacobian of vector-valued tapes is not supported currently in forward mode."
            )

        if diff_method == "parameter-shift":
            spy = mocker.spy(qml.gradients.param_shift, "transform_fn")
        elif diff_method == "finite-diff":
            spy = mocker.spy(qml.gradients.finite_diff, "transform_fn")

        a = np.array(0.1, requires_grad=True)
        b = np.array(0.2, requires_grad=True)

        dev = qml.device(dev_name, wires=2)

        @qnode(dev, interface="jax", jac_support=jac_support, diff_method=diff_method, mode=mode)
        def circuit(a, b):
            qml.RY(a, wires=0)
            qml.RX(b, wires=1)
            qml.CNOT(wires=[0, 1])
            return [qml.expval(qml.PauliZ(0)), qml.expval(qml.PauliY(1))]

        res = circuit(a, b)

        assert circuit.qtape.trainable_params == [0, 1]
        assert res.shape == (2,)

        expected = [np.cos(a), -np.cos(a) * np.sin(b)]
        assert np.allclose(res, expected, atol=tol, rtol=0)

        res = jax.jacobian(circuit, argnums=[0, 1])(a, b)
        expected = np.array([[-np.sin(a), 0], [np.sin(a) * np.sin(b), -np.cos(a) * np.cos(b)]]).T
        assert np.allclose(res, expected, atol=tol, rtol=0)

        if diff_method in ("parameter-shift", "finite-diff"):
            spy.assert_called()

    def test_jacobian_forward_mode_raises(self, dev_name, diff_method, mode, mocker, tol, jac_support):
        """Test jacobian calculation raises an error in forward mode for
        adjoint differentiation."""
        if diff_method != "adjoint" or mode != "forward" or not jac_support:
            pytest.skip(
                "Test only applicable for forward mode adjoint differentiation."
            )

        a = np.array(0.1, requires_grad=True)
        b = np.array(0.2, requires_grad=True)

        dev = qml.device(dev_name, wires=2)

        @qnode(dev, interface="jax", jac_support=jac_support, diff_method=diff_method, mode=mode)
        def circuit(a, b):
            qml.RY(a, wires=0)
            qml.RX(b, wires=1)
            qml.CNOT(wires=[0, 1])
            return [qml.expval(qml.PauliZ(0)), qml.expval(qml.PauliY(1))]

        res = circuit(a, b)

        assert circuit.qtape.trainable_params == [0, 1]
        assert res.shape == (2,)

        expected = [np.cos(a), -np.cos(a) * np.sin(b)]
        assert np.allclose(res, expected, atol=tol, rtol=0)

        with pytest.raises(ValueError):
            res = jax.jacobian(circuit, argnums=[0, 1])(a, b)

    def test_jacobian_no_evaluate(self, dev_name, diff_method, mode, mocker, tol, jac_support):
        """Test jacobian calculation when no prior circuit evaluation has been performed"""
        if diff_method != "backprop" and not jac_support:
            pytest.skip(
                "JAX interface requires either the backprop device or jacobian support to be turned on."
            )

        if mode == "forward":
            pytest.skip(
                "Computing the jacobian of vector-valued tapes is not supported currently in forward mode."
            )

        if diff_method == "parameter-shift":
            spy = mocker.spy(qml.gradients.param_shift, "transform_fn")
        elif diff_method == "finite-diff":
            spy = mocker.spy(qml.gradients.finite_diff, "transform_fn")

        a = np.array(0.1, requires_grad=True)
        b = np.array(0.2, requires_grad=True)

        dev = qml.device(dev_name, wires=2)

        @qnode(dev, interface="jax", jac_support=jac_support, diff_method=diff_method, mode=mode)
        def circuit(a, b):
            qml.RY(a, wires=0)
            qml.RX(b, wires=1)
            qml.CNOT(wires=[0, 1])
            return [qml.expval(qml.PauliZ(0)), qml.expval(qml.PauliY(1))]

        jac_fn = jax.jacobian(circuit, argnums=[0, 1])
        res = jac_fn(a, b)
        expected = np.array([[-np.sin(a), 0], [np.sin(a) * np.sin(b), -np.cos(a) * np.cos(b)]]).T
        assert np.allclose(res, expected, atol=tol, rtol=0)

        if diff_method in ("parameter-shift", "finite-diff"):
            spy.assert_called()

        # call the Jacobian with new parameters
        a = np.array(0.6, requires_grad=True)
        b = np.array(0.832, requires_grad=True)

        res = jac_fn(a, b)
        expected = np.array([[-np.sin(a), 0], [np.sin(a) * np.sin(b), -np.cos(a) * np.cos(b)]]).T
        assert np.allclose(res, expected, atol=tol, rtol=0)

    def test_jacobian_options(self, dev_name, diff_method, mode, mocker, tol, jac_support):
        """Test setting jacobian options"""
        if diff_method == "backprop":
            pytest.skip("Test does not support backprop")

        spy = mocker.spy(qml.gradients.finite_diff, "transform_fn")

        a = np.array([0.1, 0.2], requires_grad=True)

        dev = qml.device("default.qubit", wires=1)

        @qnode(dev, interface="jax", jac_support=jac_support, h=1e-8, order=2)
        def circuit(a):
            qml.RY(a[0], wires=0)
            qml.RX(a[1], wires=0)
            return qml.expval(qml.PauliZ(0))

        jax.jacobian(circuit)(a)

        for args in spy.call_args_list:
            assert args[1]["order"] == 2
            assert args[1]["h"] == 1e-8

    def test_changing_trainability(self, dev_name, diff_method, mode, mocker, tol, jac_support):
        """Test changing the trainability of parameters changes the
        number of differentiation requests made"""
        if diff_method != "parameter-shift":
            pytest.skip("Test only supports parameter-shift")

        a = jnp.array(0.1)
        b = jnp.array(0.2)

        dev = qml.device("default.qubit", wires=2)

        @qnode(dev, interface="jax", jac_support=jac_support, diff_method="parameter-shift")
        def circuit(a, b):
            qml.RY(a, wires=0)
            qml.RX(b, wires=1)
            qml.CNOT(wires=[0, 1])
            return qml.expval(qml.Hamiltonian([1, 1], [qml.PauliZ(0), qml.PauliY(1)]))

        grad_fn = jax.grad(circuit, argnums=[0, 1])
        spy = mocker.spy(qml.gradients.param_shift, "transform_fn")
        res = grad_fn(a, b)

        # the tape has reported both arguments as trainable
        assert circuit.qtape.trainable_params == [0, 1]

        expected = [-np.sin(a) + np.sin(a) * np.sin(b), -np.cos(a) * np.cos(b)]
        assert np.allclose(res, expected, atol=tol, rtol=0)

        # The parameter-shift rule has been called for each argument
        assert len(spy.spy_return[0]) == 4

        # make the second QNode argument a constant
        grad_fn = jax.grad(circuit, argnums=0)
        res = grad_fn(a, b)

        # the tape has reported only the first argument as trainable
        assert circuit.qtape.trainable_params == [0]

        expected = [-np.sin(a) + np.sin(a) * np.sin(b)]
        assert np.allclose(res, expected, atol=tol, rtol=0)

        # The parameter-shift rule has been called only once
        assert len(spy.spy_return[0]) == 2

        # trainability also updates on evaluation
        a = np.array(0.54, requires_grad=False)
        b = np.array(0.8, requires_grad=True)
        circuit(a, b)
        assert circuit.qtape.trainable_params == [1]

    def test_classical_processing(self, dev_name, diff_method, mode, tol, jac_support):
        """Test classical processing within the quantum tape"""
        a = jnp.array(0.1)
        b = jnp.array(0.2)
        c = jnp.array(0.3)

        dev = qml.device(dev_name, wires=1)

        @qnode(dev, diff_method=diff_method, interface="jax", jac_support=jac_support, mode=mode)
        def circuit(a, b, c):
            qml.RY(a * c, wires=0)
            qml.RZ(b, wires=0)
            qml.RX(c + c ** 2 + jnp.sin(a), wires=0)
            return qml.expval(qml.PauliZ(0))

        res = jax.grad(circuit, argnums=[0, 2])(a, b, c)

        if diff_method == "finite-diff":
            assert circuit.qtape.trainable_params == [0, 2]

        assert len(res) == 2

    def test_matrix_parameter(self, dev_name, diff_method, mode, tol, jac_support):
        """Test that the jax interface works correctly
        with a matrix parameter"""
        U = jnp.array([[0, 1], [1, 0]])
        a = jnp.array(0.1)

        dev = qml.device(dev_name, wires=2)

        @qnode(dev, diff_method=diff_method, interface="jax", jac_support=jac_support, mode=mode)
        def circuit(U, a):
            qml.QubitUnitary(U, wires=0)
            qml.RY(a, wires=0)
            return qml.expval(qml.PauliZ(0))

        res = jax.grad(circuit, argnums=1)(U, a)
        assert np.allclose(res, np.sin(a), atol=tol, rtol=0)

        if diff_method == "finite-diff":
            assert circuit.qtape.trainable_params == [1]

    def test_differentiable_expand(self, dev_name, diff_method, mode, tol, jac_support):
        """Test that operation and nested tape expansion
        is differentiable"""

        class U3(qml.U3):
            def expand(self):
                theta, phi, lam = self.data
                wires = self.wires

                with JacobianTape() as tape:
                    qml.Rot(lam, theta, -lam, wires=wires)
                    qml.PhaseShift(phi + lam, wires=wires)

                return tape

        dev = qml.device(dev_name, wires=1)
        a = jnp.array(0.1)
        p = jnp.array([0.1, 0.2, 0.3])

        @qnode(dev, diff_method=diff_method, interface="jax", jac_support=jac_support, mode=mode)
        def circuit(a, p):
            qml.RX(a, wires=0)
            U3(p[0], p[1], p[2], wires=0)
            return qml.expval(qml.PauliX(0))

        res = circuit(a, p)
        expected = np.cos(a) * np.cos(p[1]) * np.sin(p[0]) + np.sin(a) * (
            np.cos(p[2]) * np.sin(p[1]) + np.cos(p[0]) * np.cos(p[1]) * np.sin(p[2])
        )
        assert np.allclose(res, expected, atol=tol, rtol=0)

        res = jax.grad(circuit, argnums=1)(a, p)
        expected = np.array(
            [
                np.cos(p[1]) * (np.cos(a) * np.cos(p[0]) - np.sin(a) * np.sin(p[0]) * np.sin(p[2])),
                np.cos(p[1]) * np.cos(p[2]) * np.sin(a)
                - np.sin(p[1])
                * (np.cos(a) * np.sin(p[0]) + np.cos(p[0]) * np.sin(a) * np.sin(p[2])),
                np.sin(a)
                * (np.cos(p[0]) * np.cos(p[1]) * np.cos(p[2]) - np.sin(p[1]) * np.sin(p[2])),
            ]
        )
        assert np.allclose(res, expected, atol=tol, rtol=0)


@pytest.mark.parametrize("jac_support", [None, True])
class TestShotsIntegration:
    """Test that the QNode correctly changes shot value, and
    remains differentiable."""

    def test_changing_shots(self, mocker, tol, jac_support):
        """Test that changing shots works on execution"""
        dev = qml.device("default.qubit", wires=2, shots=None)
        a, b = jnp.array([0.543, -0.654])

        @qnode(dev, diff_method=qml.gradients.param_shift, interface="jax", jac_support=jac_support)
        def circuit(a, b):
            qml.RY(a, wires=0)
            qml.RX(b, wires=1)
            qml.CNOT(wires=[0, 1])
            return qml.expval(qml.PauliY(1))

        spy = mocker.spy(dev, "sample")

        # execute with device default shots (None)
        res = circuit(a, b)
        assert np.allclose(res, -np.cos(a) * np.sin(b), atol=tol, rtol=0)
        spy.assert_not_called()

        # execute with shots=100
        res = circuit(a, b, shots=100)
        spy.assert_called()
        assert spy.spy_return.shape == (100,)

        # device state has been unaffected
        assert dev.shots is None
        spy = mocker.spy(dev, "sample")
        res = circuit(a, b)
        assert np.allclose(res, -np.cos(a) * np.sin(b), atol=tol, rtol=0)
        spy.assert_not_called()

    def test_gradient_integration(self, tol, jac_support):
        """Test that temporarily setting the shots works
        for gradient computations"""
        dev = qml.device("default.qubit", wires=2, shots=100)
        a, b = jnp.array([0.543, -0.654])

        @qnode(dev, diff_method=qml.gradients.param_shift, interface="jax", jac_support=jac_support)
        def cost_fn(a, b):
            qml.RY(a, wires=0)
            qml.RX(b, wires=1)
            qml.CNOT(wires=[0, 1])
            return qml.expval(qml.PauliY(1))

        res = jax.grad(cost_fn, argnums=[0, 1])(a, b, shots=30000)
        assert dev.shots == 100

        expected = [np.sin(a) * np.sin(b), -np.cos(a) * np.cos(b)]
        assert np.allclose(res, expected, atol=0.1, rtol=0)

    def test_update_diff_method(self, mocker, tol, jac_support):
        """Test that temporarily setting the shots updates the diff method"""
        dev = qml.device("default.qubit", wires=2, shots=100)
        a, b = jnp.array([0.543, -0.654])

        spy = mocker.spy(qml, "execute")

        @qnode(dev, interface="jax", jac_support=jac_support)
        def cost_fn(a, b):
            qml.RY(a, wires=0)
            qml.RX(b, wires=1)
            qml.CNOT(wires=[0, 1])
            return qml.expval(qml.PauliY(1))

        # since we are using finite shots, parameter-shift will
        # be chosen
        assert cost_fn.gradient_fn is qml.gradients.param_shift

        cost_fn(a, b)
        assert spy.call_args[1]["gradient_fn"] is qml.gradients.param_shift

        # if we set the shots to None, backprop can now be used
        cost_fn(a, b, shots=None)
        assert spy.call_args[1]["gradient_fn"] == "backprop"

        # original QNode settings are unaffected
        assert cost_fn.gradient_fn is qml.gradients.param_shift
        cost_fn(a, b)
        assert spy.call_args[1]["gradient_fn"] is qml.gradients.param_shift


@pytest.mark.parametrize("dev_name,diff_method,mode", qubit_device_and_diff_method)
@pytest.mark.parametrize("jac_support", [None, True])
class TestQubitIntegration:
    """Tests that ensure various qubit circuits integrate correctly"""

    def test_probability_differentiation(self, dev_name, diff_method, mode, tol, jac_support):
        """Tests correct output shape and evaluation for a tape
        with a single prob output"""
        if diff_method != "backprop" and not jac_support:
            pytest.skip(
                "JAX interface requires either the backprop device or jacobian support to be turned on."
            )

        if diff_method == "adjoint":
            pytest.skip("Adjoint does not support qml.probs")

        dev = qml.device(dev_name, wires=2)
        x = jnp.array(0.543)
        y = jnp.array(-0.654)

        # @qnode(dev, diff_method=diff_method, interface="jax", jac_support=jac_support, mode=mode)
        def circuit(x, y):
            qml.RX(x, wires=[0])
            qml.RY(y, wires=[1])
            qml.CNOT(wires=[0, 1])
            return qml.probs(wires=[0, 1])

        jax_qnode = qml.QNode(
            circuit,
            dev,
            diff_method=diff_method,
            interface="jax",
            jac_support=jac_support,
            mode=mode,
        )
        autograd_qnode = qml.QNode(
            circuit, dev, diff_method=diff_method, interface="autograd", mode=mode
        )
        x_, y_ = np.asarray(x), np.asarray(y)
        exp = qml.jacobian(autograd_qnode, argnum=[0, 1])(x_, y_)
        res = jax.jacobian(jax_qnode, argnums=[0, 1])(x, y)

        expected = np.array(
            [
                [-np.sin(x) * np.cos(y) / 2, -np.cos(x) * np.sin(y) / 2],
                [np.cos(y) * np.sin(x) / 2, np.cos(x) * np.sin(y) / 2],
            ]
        )
        assert np.allclose(res, exp, atol=tol, rtol=0)

    def test_probability_jac_with_autograd(self, dev_name, diff_method, mode, tol, jac_support):
        """Tests correct output shape and evaluation for a tape
        with a single prob output"""
        if diff_method != "backprop" and not jac_support:
            pytest.skip(
                "JAX interface requires either the backprop device or jacobian support to be turned on."
            )

        if diff_method == "adjoint":
            pytest.skip("Adjoint does not support qml.probs")

        dev = qml.device(dev_name, wires=2)
        x = jnp.array(0.543)
        y = jnp.array(-0.654)

        def circuit(x, y):
            qml.RX(x, wires=[0])
            qml.RY(y, wires=[1])
            qml.CNOT(wires=[0, 1])
            return qml.probs(wires=[0, 1])

        jax_qnode = qml.QNode(
            circuit,
            dev,
            diff_method=diff_method,
            interface="jax",
            jac_support=jac_support,
            mode=mode,
        )
        autograd_qnode = qml.QNode(
            circuit, dev, diff_method=diff_method, interface="autograd", mode=mode
        )

        x_, y_ = np.asarray(x), np.asarray(y)
        exp = qml.jacobian(autograd_qnode, argnum=[0, 1])(x_, y_)
        res = jax.jacobian(jax_qnode, argnums=[0, 1])(x, y)

        assert np.allclose(res, exp, atol=tol, rtol=0)

    def test_multiple_probability_differentiation(
        self, dev_name, diff_method, mode, tol, jac_support
    ):
        """Tests correct output shape and evaluation for a tape
        with multiple prob outputs"""
        if diff_method != "backprop" and not jac_support:
            pytest.skip(
                "JAX interface requires either the backprop device or jacobian support to be turned on."
            )

        if diff_method == "adjoint":
            pytest.skip("Adjoint does not support qml.probs")

        dev = qml.device(dev_name, wires=2)
        x = jnp.array(0.543)
        y = jnp.array(-0.654)

        @qnode(dev, diff_method=diff_method, interface="jax", jac_support=jac_support, mode=mode)
        def circuit(x, y):
            qml.RX(x, wires=[0])
            qml.RY(y, wires=[1])
            qml.CNOT(wires=[0, 1])
            return qml.probs(wires=[0]), qml.probs(wires=[1])

        res = circuit(x, y)

        expected = np.array(
            [
                [np.cos(x / 2) ** 2, np.sin(x / 2) ** 2],
                [(1 + np.cos(x) * np.cos(y)) / 2, (1 - np.cos(x) * np.cos(y)) / 2],
            ]
        )
        assert np.allclose(res, expected, atol=tol, rtol=0)

        if diff_method in ("parameter-shift", "finite-diff"):

            res = jax.jacobian(circuit, argnums=[0, 1])(x, y)

            # TODO: remove the swapping of axes when custom gradient outputs
            # have been adjusted
            res = tuple(r.swapaxes(0, 1) for r in res)
        else:
            res = jax.jacobian(circuit, argnums=[0, 1])(x, y)

        expected = np.array(
            [
                [
                    [-np.sin(x) / 2, np.sin(x) / 2],
                    [-np.cos(y) * np.sin(x) / 2, np.sin(x) * np.cos(y) / 2],
                ],
                [
                    [0, 0],
                    [-np.cos(x) * np.sin(y) / 2, np.cos(x) * np.sin(y) / 2],
                ],
            ]
        )

        assert np.allclose(res, expected, atol=tol, rtol=0)

    @pytest.mark.xfail(reason="Line 230 in QubitDevice: results = self._asarray(results) fails")
    def test_ragged_differentiation(self, dev_name, diff_method, mode, tol, jac_support):
        """Tests correct output shape and evaluation for a tape
        with prob and expval outputs"""
        if diff_method != "backprop" and not jac_support:
            pytest.skip(
                "JAX interface requires either the backprop device or jacobian support to be turned on."
            )

        dev = qml.device(dev_name, wires=2)
        x = jnp.array(0.543)
        y = jnp.array(-0.654)

        @qnode(dev, diff_method=diff_method, interface="jax", jac_support=jac_support, mode=mode)
        def circuit(x, y):
            qml.RX(x, wires=[0])
            qml.RY(y, wires=[1])
            qml.CNOT(wires=[0, 1])
            return [qml.expval(qml.PauliZ(0)), qml.probs(wires=[1])]

        res = circuit(x, y)

        expected = np.array(
            [np.cos(x), (1 + np.cos(x) * np.cos(y)) / 2, (1 - np.cos(x) * np.cos(y)) / 2]
        )
        assert np.allclose(res, expected, atol=tol, rtol=0)

        res = jax.jacobian(circuit, argnums=[0, 1])(x, y)
        expected = np.array(
            [
                [-np.sin(x), 0],
                [-np.sin(x) * np.cos(y) / 2, -np.cos(x) * np.sin(y) / 2],
                [np.cos(y) * np.sin(x) / 2, np.cos(x) * np.sin(y) / 2],
            ]
        )
        assert np.allclose(res, expected, atol=tol, rtol=0)

    @pytest.mark.xfail(reason="Line 230 in QubitDevice: results = self._asarray(results) fails")
    def test_ragged_differentiation_variance(self, dev_name, diff_method, mode, tol, jac_support):
        """Tests correct output shape and evaluation for a tape
        with prob and variance outputs"""
        if diff_method != "backprop" and not jac_support:
            pytest.skip(
                "JAX interface requires either the backprop device or jacobian support to be turned on."
            )

        dev = qml.device(dev_name, wires=2)
        x = jnp.array(0.543)
        y = jnp.array(-0.654)

        @qnode(dev, diff_method=diff_method, interface="jax", jac_support=jac_support, mode=mode)
        def circuit(x, y):
            qml.RX(x, wires=[0])
            qml.RY(y, wires=[1])
            qml.CNOT(wires=[0, 1])
            return [qml.var(qml.PauliZ(0)), qml.probs(wires=[1])]

        res = circuit(x, y)

        expected = np.array(
            [np.sin(x) ** 2, (1 + np.cos(x) * np.cos(y)) / 2, (1 - np.cos(x) * np.cos(y)) / 2]
        )
        assert np.allclose(res, expected, atol=tol, rtol=0)

        res = jax.jacobian(circuit, argnums=[0, 1])(x, y)
        expected = np.array(
            [
                [2 * np.cos(x) * np.sin(x), 0],
                [-np.sin(x) * np.cos(y) / 2, -np.cos(x) * np.sin(y) / 2],
                [np.cos(y) * np.sin(x) / 2, np.cos(x) * np.sin(y) / 2],
            ]
        )
        assert np.allclose(res, expected, atol=tol, rtol=0)

    def test_sampling(self, dev_name, diff_method, mode, jac_support):
        """Test sampling works as expected"""
        if diff_method != "backprop" and not jac_support:
            pytest.skip(
                "JAX interface requires either the backprop device or jacobian support to be turned on."
            )

        if mode == "forward":
            pytest.skip("Sampling not possible with forward mode differentiation.")

        if diff_method == "adjoint":
            pytest.skip("Sampling not possible with adjoint differentiation.")

        dev = qml.device(dev_name, wires=2, shots=10)

        @qnode(dev, diff_method=diff_method, interface="jax", jac_support=jac_support, mode=mode)
        def circuit():
            qml.Hadamard(wires=[0])
            qml.CNOT(wires=[0, 1])
            return [qml.sample(qml.PauliZ(0)), qml.sample(qml.PauliX(1))]

        res = circuit()

        assert res.shape == (2, 10)
        assert isinstance(res, jnp.DeviceArray)

    def test_chained_qnodes(self, dev_name, diff_method, mode, jac_support):
        """Test that the gradient of chained QNodes works without error"""
        dev = qml.device(dev_name, wires=2)

        class Template(qml.templates.StronglyEntanglingLayers):
            def expand(self):
                with qml.tape.QuantumTape() as tape:
                    qml.templates.StronglyEntanglingLayers(*self.parameters, self.wires)
                return tape

        @qnode(dev, interface="jax", jac_support=jac_support, diff_method=diff_method)
        def circuit1(weights):
            Template(weights, wires=[0, 1])
            return qml.expval(qml.PauliZ(0))

        @qnode(dev, interface="jax", jac_support=jac_support, diff_method=diff_method)
        def circuit2(data, weights):
            qml.templates.AngleEmbedding(jnp.stack([data, 0.7]), wires=[0, 1])
            Template(weights, wires=[0, 1])
            return qml.expval(qml.PauliX(0))

        def cost(weights):
            w1, w2 = weights
            c1 = circuit1(w1)
            c2 = circuit2(c1, w2)
            return jnp.sum(c2) ** 2

        w1 = qml.templates.StronglyEntanglingLayers.shape(n_wires=2, n_layers=3)
        w2 = qml.templates.StronglyEntanglingLayers.shape(n_wires=2, n_layers=4)

        weights = [
            jnp.array(np.random.random(w1)),
            jnp.array(np.random.random(w2)),
        ]

        grad_fn = jax.grad(cost)
        res = grad_fn(weights)

        assert len(res) == 2

    def test_second_derivative(self, dev_name, diff_method, mode, tol, jac_support):
        """Test second derivative calculation of a scalar valued QNode"""
        if diff_method not in {"backprop"}:
            pytest.skip("Test only supports backprop")

        dev = qml.device(dev_name, wires=1)

        @qnode(
            dev,
            diff_method=diff_method,
            interface="jax",
            jac_support=jac_support,
            mode=mode,
            max_diff=2,
        )
        def circuit(x):
            qml.RY(x[0], wires=0)
            qml.RX(x[1], wires=0)
            return qml.expval(qml.PauliZ(0))

        x = jnp.array([1.0, 2.0])
        res = circuit(x)
        g = jax.grad(circuit)(x)
        g2 = jax.grad(lambda x: jnp.sum(jax.grad(circuit)(x)))(x)

        a, b = x

        expected_res = np.cos(a) * np.cos(b)
        assert np.allclose(res, expected_res, atol=tol, rtol=0)

        expected_g = [-np.sin(a) * np.cos(b), -np.cos(a) * np.sin(b)]
        assert np.allclose(g, expected_g, atol=tol, rtol=0)

        expected_g2 = [
            -np.cos(a) * np.cos(b) + np.sin(a) * np.sin(b),
            np.sin(a) * np.sin(b) - np.cos(a) * np.cos(b),
        ]
        assert np.allclose(g2, expected_g2, atol=tol, rtol=0)

    def test_hessian(self, dev_name, diff_method, mode, tol, jac_support):
        """Test hessian calculation of a scalar valued QNode"""
        if diff_method not in {"backprop"}:
            pytest.skip("Test only supports  backprop")

        dev = qml.device(dev_name, wires=1)

        @qnode(
            dev,
            diff_method=diff_method,
            interface="jax",
            jac_support=jac_support,
            mode=mode,
            max_diff=2,
        )
        def circuit(x):
            qml.RY(x[0], wires=0)
            qml.RX(x[1], wires=0)
            return qml.expval(qml.PauliZ(0))

        x = jnp.array([1.0, 2.0])
        res = circuit(x)

        a, b = x

        expected_res = np.cos(a) * np.cos(b)
        assert np.allclose(res, expected_res, atol=tol, rtol=0)

        grad_fn = jax.grad(circuit)
        g = grad_fn(x)

        expected_g = [-np.sin(a) * np.cos(b), -np.cos(a) * np.sin(b)]
        assert np.allclose(g, expected_g, atol=tol, rtol=0)

        hess = jax.jacobian(grad_fn)(x)

        expected_hess = [
            [-np.cos(a) * np.cos(b), np.sin(a) * np.sin(b)],
            [np.sin(a) * np.sin(b), -np.cos(a) * np.cos(b)],
        ]
        assert np.allclose(hess, expected_hess, atol=tol, rtol=0)

    def test_hessian_vector_valued(self, dev_name, diff_method, mode, tol, jac_support):
        """Test hessian calculation of a vector valued QNode"""
        if diff_method not in {"backprop"}:
            pytest.skip("Test only supports backprop")

        dev = qml.device(dev_name, wires=1)

        @qnode(
            dev,
            diff_method=diff_method,
            interface="jax",
            jac_support=jac_support,
            mode=mode,
            max_diff=2,
        )
        def circuit(x):
            qml.RY(x[0], wires=0)
            qml.RX(x[1], wires=0)
            return qml.probs(wires=0)

        x = jnp.array([1.0, 2.0])
        res = circuit(x)

        a, b = x

        expected_res = [0.5 + 0.5 * np.cos(a) * np.cos(b), 0.5 - 0.5 * np.cos(a) * np.cos(b)]
        assert np.allclose(res, expected_res, atol=tol, rtol=0)

        jac_fn = jax.jacobian(circuit)
        g = jac_fn(x)

        expected_g = [
            [-0.5 * np.sin(a) * np.cos(b), -0.5 * np.cos(a) * np.sin(b)],
            [0.5 * np.sin(a) * np.cos(b), 0.5 * np.cos(a) * np.sin(b)],
        ]
        assert np.allclose(g, expected_g, atol=tol, rtol=0)

        hess = jax.jacobian(jac_fn)(x)

        expected_hess = [
            [
                [-0.5 * np.cos(a) * np.cos(b), 0.5 * np.sin(a) * np.sin(b)],
                [0.5 * np.sin(a) * np.sin(b), -0.5 * np.cos(a) * np.cos(b)],
            ],
            [
                [0.5 * np.cos(a) * np.cos(b), -0.5 * np.sin(a) * np.sin(b)],
                [-0.5 * np.sin(a) * np.sin(b), 0.5 * np.cos(a) * np.cos(b)],
            ],
        ]
        assert np.allclose(hess, expected_hess, atol=tol, rtol=0)

    def test_hessian_vector_valued_postprocessing(
        self, dev_name, diff_method, mode, tol, jac_support
    ):
        """Test hessian calculation of a vector valued QNode with post-processing"""
        if diff_method not in {"backprop"}:
            pytest.skip("Test only supports backprop")

        dev = qml.device(dev_name, wires=1)

        @qnode(
            dev,
            diff_method=diff_method,
            interface="jax",
            jac_support=jac_support,
            mode=mode,
            max_diff=2,
        )
        def circuit(x):
            qml.RX(x[0], wires=0)
            qml.RY(x[1], wires=0)
            return [qml.expval(qml.PauliZ(0)), qml.expval(qml.PauliZ(0))]

        def cost_fn(x):
            return x @ circuit(x)

        x = jnp.array(
            [0.76, -0.87],
        )
        res = cost_fn(x)

        a, b = x

        expected_res = x @ jnp.array([np.cos(a) * np.cos(b), np.cos(a) * np.cos(b)])
        assert np.allclose(res, expected_res, atol=tol, rtol=0)

        grad_fn = jax.grad(cost_fn)
        g = grad_fn(x)

        expected_g = [
            np.cos(b) * (np.cos(a) - (a + b) * np.sin(a)),
            np.cos(a) * (np.cos(b) - (a + b) * np.sin(b)),
        ]
        assert np.allclose(g, expected_g, atol=tol, rtol=0)
        hess = jax.jacobian(grad_fn)(x)

        expected_hess = [
            [
                -(np.cos(b) * ((a + b) * np.cos(a) + 2 * np.sin(a))),
                -(np.cos(b) * np.sin(a)) + (-np.cos(a) + (a + b) * np.sin(a)) * np.sin(b),
            ],
            [
                -(np.cos(b) * np.sin(a)) + (-np.cos(a) + (a + b) * np.sin(a)) * np.sin(b),
                -(np.cos(a) * ((a + b) * np.cos(b) + 2 * np.sin(b))),
            ],
        ]

        assert np.allclose(hess, expected_hess, atol=tol, rtol=0)

    def test_hessian_vector_valued_separate_args(
        self, dev_name, diff_method, mode, mocker, tol, jac_support
    ):
        """Test hessian calculation of a vector valued QNode that has separate input arguments"""
        if diff_method not in {"backprop"}:
            pytest.skip("Test only supports backprop")

        dev = qml.device(dev_name, wires=1)

        @qnode(
            dev,
            diff_method=diff_method,
            interface="jax",
            jac_support=jac_support,
            mode=mode,
            max_diff=2,
        )
        def circuit(a, b):
            qml.RY(a, wires=0)
            qml.RX(b, wires=0)
            return qml.probs(wires=0)

        a = jnp.array(1.0)
        b = jnp.array(2.0)
        res = circuit(a, b)

        expected_res = [0.5 + 0.5 * np.cos(a) * np.cos(b), 0.5 - 0.5 * np.cos(a) * np.cos(b)]
        assert np.allclose(res, expected_res, atol=tol, rtol=0)

        jac_fn = jax.jacobian(circuit, argnums=[0, 1])
        g = jac_fn(a, b)

        expected_g = np.array(
            [
                [-0.5 * np.sin(a) * np.cos(b), -0.5 * np.cos(a) * np.sin(b)],
                [0.5 * np.sin(a) * np.cos(b), 0.5 * np.cos(a) * np.sin(b)],
            ]
        )
        assert np.allclose(g, expected_g.T, atol=tol, rtol=0)

        spy = mocker.spy(qml.gradients.param_shift, "transform_fn")
        hess = jax.jacobian(jac_fn, argnums=[0, 1])(a, b)

        if diff_method == "backprop":
            spy.assert_not_called()
        elif diff_method == "parameter-shift":
            spy.assert_called()

        expected_hess = np.array(
            [
                [
                    [-0.5 * np.cos(a) * np.cos(b), 0.5 * np.cos(a) * np.cos(b)],
                    [0.5 * np.sin(a) * np.sin(b), -0.5 * np.sin(a) * np.sin(b)],
                ],
                [
                    [0.5 * np.sin(a) * np.sin(b), -0.5 * np.sin(a) * np.sin(b)],
                    [-0.5 * np.cos(a) * np.cos(b), 0.5 * np.cos(a) * np.cos(b)],
                ],
            ]
        )
        assert np.allclose(hess, expected_hess, atol=tol, rtol=0)

    def test_state(self, dev_name, diff_method, mode, tol, jac_support):
        """Test that the state can be returned and differentiated"""
        if diff_method != "backprop" and not jac_support:
            pytest.skip(
                "JAX interface requires either the backprop device or jacobian support to be turned on."
            )

        if diff_method == "adjoint":
            pytest.skip("Adjoint does not support states")

        dev = qml.device(dev_name, wires=2)

        x = jnp.array(0.543)
        y = jnp.array(-0.654)

        @qnode(dev, diff_method=diff_method, interface="jax", jac_support=jac_support, mode=mode)
        def circuit(x, y):
            qml.RX(x, wires=[0])
            qml.RY(y, wires=[1])
            qml.CNOT(wires=[0, 1])
            return qml.state()

        def cost_fn(x, y):
            res = circuit(x, y)
            assert res.dtype is np.dtype("complex128")
            probs = jnp.abs(res) ** 2
            return probs[0] + probs[2]

        res = cost_fn(x, y)

        if diff_method not in {"backprop"}:
            pytest.skip("Test only supports backprop")

        res = jax.grad(cost_fn, argnums=[0, 1])(x, y)
        expected = np.array([-np.sin(x) * np.cos(y) / 2, -np.cos(x) * np.sin(y) / 2])
        assert np.allclose(res, expected, atol=tol, rtol=0)

    def test_projector(self, dev_name, diff_method, mode, tol, jac_support):
        """Test that the variance of a projector is correctly returned"""
        if diff_method == "adjoint":
            pytest.skip("Adjoint does not support projectors")

        dev = qml.device(dev_name, wires=2)
        P = jnp.array([1])
        x, y = 0.765, -0.654

        @qnode(dev, diff_method=diff_method, interface="jax", jac_support=jac_support, mode=mode)
        def circuit(x, y):
            qml.RX(x, wires=0)
            qml.RY(y, wires=1)
            qml.CNOT(wires=[0, 1])
            return qml.var(qml.Projector(P, wires=0) @ qml.PauliX(1))

        res = circuit(x, y)
        expected = 0.25 * np.sin(x / 2) ** 2 * (3 + np.cos(2 * y) + 2 * np.cos(x) * np.sin(y) ** 2)
        assert np.allclose(res, expected, atol=tol, rtol=0)

        res = jax.grad(circuit, argnums=[0, 1])(x, y)
        expected = np.array(
            [
                0.5 * np.sin(x) * (np.cos(x / 2) ** 2 + np.cos(2 * y) * np.sin(x / 2) ** 2),
                -2 * np.cos(y) * np.sin(x / 2) ** 4 * np.sin(y),
            ]
        )
        assert np.allclose(res, expected, atol=tol, rtol=0)


@pytest.mark.parametrize(
    "diff_method,kwargs",
    [["finite-diff", {}], ("parameter-shift", {}), ("parameter-shift", {"force_order2": True})],
)
@pytest.mark.parametrize("jac_support", [None, True])
class TestCV:
    """Tests for CV integration"""

    def test_first_order_observable(self, diff_method, kwargs, tol, jac_support):
        """Test variance of a first order CV observable"""
        dev = qml.device("default.gaussian", wires=1)

        r = 0.543
        phi = -0.654

        @qnode(dev, interface="jax", jac_support=jac_support, diff_method=diff_method, **kwargs)
        def circuit(r, phi):
            qml.Squeezing(r, 0, wires=0)
            qml.Rotation(phi, wires=0)
            return qml.var(qml.X(0))

        res = circuit(r, phi)
        expected = np.exp(2 * r) * np.sin(phi) ** 2 + np.exp(-2 * r) * np.cos(phi) ** 2
        assert np.allclose(res, expected, atol=tol, rtol=0)

        # circuit jacobians
        res = jax.grad(circuit, argnums=[0, 1])(r, phi)
        expected = np.array(
            [
                2 * np.exp(2 * r) * np.sin(phi) ** 2 - 2 * np.exp(-2 * r) * np.cos(phi) ** 2,
                2 * np.sinh(2 * r) * np.sin(2 * phi),
            ]
        )
        assert np.allclose(res, expected, atol=tol, rtol=0)

    def test_second_order_observable(self, diff_method, kwargs, tol, jac_support):
        """Test variance of a second order CV expectation value"""
        dev = qml.device("default.gaussian", wires=1)

        n = 0.12
        a = 0.765

        @qnode(dev, interface="jax", jac_support=jac_support, diff_method=diff_method, **kwargs)
        def circuit(n, a):
            qml.ThermalState(n, wires=0)
            qml.Displacement(a, 0, wires=0)
            return qml.var(qml.NumberOperator(0))

        res = circuit(n, a)
        expected = n ** 2 + n + np.abs(a) ** 2 * (1 + 2 * n)
        assert np.allclose(res, expected, atol=tol, rtol=0)

        # circuit jacobians
        res = jax.grad(circuit, argnums=[0, 1])(n, a)
        expected = np.array([2 * a ** 2 + 2 * n + 1, 2 * a * (2 * n + 1)])
        assert np.allclose(res, expected, atol=tol, rtol=0)


@pytest.mark.parametrize("jac_support", [None, True])
def test_adjoint_reuse_device_state(mocker, jac_support):
    """Tests that the jax interface reuses the device state for adjoint differentiation"""
    dev = qml.device("default.qubit", wires=1)

    @qnode(dev, interface="jax", jac_support=jac_support, diff_method="adjoint")
    def circ(x):
        qml.RX(x, wires=0)
        return qml.expval(qml.PauliZ(0))

    spy = mocker.spy(dev, "adjoint_jacobian")

    grad = jax.grad(circ)(1.0)
    assert circ.device.num_executions == 1

    spy.assert_called_with(mocker.ANY, use_device_state=True)


@pytest.mark.parametrize("dev_name,diff_method,mode", qubit_device_and_diff_method)
@pytest.mark.parametrize("jac_support", [None, True])
class TestTapeExpansion:
    """Test that tape expansion within the QNode integrates correctly
    with the JAX interface"""

    @pytest.mark.parametrize("max_diff", [1, 2])
    def test_gradient_expansion_trainable_only(
        self, dev_name, diff_method, mode, max_diff, mocker, jac_support
    ):
        """Test that a *supported* operation with no gradient recipe is only
        expanded for parameter-shift and finite-differences when it is trainable."""
        if diff_method not in ("parameter-shift", "finite-diff"):
            pytest.skip("Only supports gradient transforms")

        if max_diff > 1:
            pytest.skip("JAX only supports first derivatives")

        dev = qml.device(dev_name, wires=1)

        class PhaseShift(qml.PhaseShift):
            grad_method = None

            def expand(self):
                with qml.tape.QuantumTape() as tape:
                    qml.RY(3 * self.data[0], wires=self.wires)
                return tape

        @qnode(
            dev,
            diff_method=diff_method,
            mode=mode,
            max_diff=max_diff,
            interface="jax",
            jac_support=jac_support,
        )
        def circuit(x, y):
            qml.Hadamard(wires=0)
            PhaseShift(x, wires=0)
            PhaseShift(2 * y, wires=0)
            return qml.expval(qml.PauliX(0))

        spy = mocker.spy(circuit.device, "batch_execute")
        x = jnp.array(0.5)
        y = jnp.array(0.7)
        circuit(x, y)

        spy = mocker.spy(circuit.gradient_fn, "transform_fn")
        res = jax.grad(circuit, argnums=[0])(x, y)

        input_tape = spy.call_args[0][0]
        assert len(input_tape.operations) == 3
        assert input_tape.operations[1].name == "RY"
        assert input_tape.operations[1].data[0] == 3 * x
        assert input_tape.operations[2].name == "PhaseShift"
        assert input_tape.operations[2].grad_method is None

    @pytest.mark.parametrize("max_diff", [1, 2])
    def test_hamiltonian_expansion_analytic(
        self, dev_name, diff_method, mode, max_diff, mocker, jac_support
    ):
        """Test that the Hamiltonian is not expanded if there
        are non-commuting groups and the number of shots is None
        and the first and second order gradients are correctly evaluated"""
        if diff_method == "adjoint":
            pytest.skip("The adjoint method does not yet support Hamiltonians")

        if max_diff > 1:
            pytest.skip("JAX only supports first derivatives")

        dev = qml.device(dev_name, wires=3, shots=None)
        spy = mocker.spy(qml.transforms, "hamiltonian_expand")
        obs = [qml.PauliX(0), qml.PauliX(0) @ qml.PauliZ(1), qml.PauliZ(0) @ qml.PauliZ(1)]

        @qnode(
            dev,
            interface="jax",
            jac_support=jac_support,
            diff_method=diff_method,
            mode=mode,
            max_diff=max_diff,
        )
        def circuit(data, weights, coeffs):
            weights = weights.reshape(1, -1)
            qml.templates.AngleEmbedding(data, wires=[0, 1])
            qml.templates.BasicEntanglerLayers(weights, wires=[0, 1])
            return qml.expval(qml.Hamiltonian(coeffs, obs))

        d = jnp.array([0.1, 0.2])
        w = jnp.array([0.654, -0.734])
        c = jnp.array([-0.6543, 0.24, 0.54])

        # test output
        res = circuit(d, w, c)
        expected = c[2] * np.cos(d[1] + w[1]) - c[1] * np.sin(d[0] + w[0]) * np.sin(d[1] + w[1])
        assert np.allclose(res, expected)
        spy.assert_not_called()

        # test gradients
        grad = jax.grad(circuit, argnums=[1, 2])(d, w, c)
        expected_w = [
            -c[1] * np.cos(d[0] + w[0]) * np.sin(d[1] + w[1]),
            -c[1] * np.cos(d[1] + w[1]) * np.sin(d[0] + w[0]) - c[2] * np.sin(d[1] + w[1]),
        ]
        expected_c = [0, -np.sin(d[0] + w[0]) * np.sin(d[1] + w[1]), np.cos(d[1] + w[1])]
        assert np.allclose(grad[0], expected_w)
        assert np.allclose(grad[1], expected_c)

        # test second-order derivatives
        if diff_method in ("parameter-shift", "backprop") and max_diff == 2:

            grad2_c = jax.jacobian(jax.grad(circuit, argnum=2), argnum=2)(d, w, c)
            assert np.allclose(grad2_c, 0)

            grad2_w_c = jax.jacobian(jax.grad(circuit, argnum=1), argnum=2)(d, w, c)
            expected = [0, -np.cos(d[0] + w[0]) * np.sin(d[1] + w[1]), 0], [
                0,
                -np.cos(d[1] + w[1]) * np.sin(d[0] + w[0]),
                -np.sin(d[1] + w[1]),
            ]
            assert np.allclose(grad2_w_c, expected)

    # @pytest.mark.xfail(reason="Will fail since expval(H) expands to a vector valued return for finite-shots")
    # @pytest.mark.parametrize("max_diff", [1, 2])
    # def test_hamiltonian_expansion_finite_shots(
    #     self, dev_name, diff_method, mode, max_diff, mocker
    # ):
    #     """Test that the Hamiltonian is expanded if there
    #     are non-commuting groups and the number of shots is finite
    #     and the first and second order gradients are correctly evaluated"""
    #     if diff_method in ("adjoint", "backprop", "finite-diff"):
    #         pytest.skip("The adjoint and backprop methods do not yet support sampling")

    #     if max_diff > 1:
    #         pytest.skip("JAX only supports first derivatives")

    #     dev = qml.device(dev_name, wires=3, shots=50000)
    #     spy = mocker.spy(qml.transforms, "hamiltonian_expand")
    #     obs = [qml.PauliX(0), qml.PauliX(0) @ qml.PauliZ(1), qml.PauliZ(0) @ qml.PauliZ(1)]

    #     @qnode(dev, interface="jax", jac_support=jac_support, diff_method=diff_method, mode=mode, max_diff=max_diff)
    #     def circuit(data, weights, coeffs):
    #         weights = weights.reshape(1, -1)
    #         qml.templates.AngleEmbedding(data, wires=[0, 1])
    #         qml.templates.BasicEntanglerLayers(weights, wires=[0, 1])
    #         H = qml.Hamiltonian(coeffs, obs)
    #         H.compute_grouping()
    #         return qml.expval(H)

    #     d = jnp.array([0.1, 0.2])
    #     w = jnp.array([0.654, -0.734])
    #     c = jnp.array([-0.6543, 0.24, 0.54])

    #     # test output
    #     res = circuit(d, w, c)
    #     expected = c[2] * np.cos(d[1] + w[1]) - c[1] * np.sin(d[0] + w[0]) * np.sin(d[1] + w[1])
    #     assert np.allclose(res, expected, atol=0.1)
    #     spy.assert_called()

    #     # test gradients
    #     grad = jax.grad(circuit, argnums=[1, 2])(d, w, c)
    #     expected_w = [
    #         -c[1] * np.cos(d[0] + w[0]) * np.sin(d[1] + w[1]),
    #         -c[1] * np.cos(d[1] + w[1]) * np.sin(d[0] + w[0]) - c[2] * np.sin(d[1] + w[1]),
    #     ]
    #     expected_c = [0, -np.sin(d[0] + w[0]) * np.sin(d[1] + w[1]), np.cos(d[1] + w[1])]
    #     assert np.allclose(grad[0], expected_w, atol=0.1)
    #     assert np.allclose(grad[1], expected_c, atol=0.1)

    #     # test second-order derivatives
    #     if diff_method == "parameter-shift" and max_diff == 2:

    #         grad2_c = jax.jacobian(jax.grad(circuit, argnum=2), argnum=2)(d, w, c)
    #         assert np.allclose(grad2_c, 0, atol=0.1)

    #         grad2_w_c = jax.jacobian(jax.grad(circuit, argnum=1), argnum=2)(d, w, c)
    #         expected = [0, -np.cos(d[0] + w[0]) * np.sin(d[1] + w[1]), 0], [
    #             0,
    #             -np.cos(d[1] + w[1]) * np.sin(d[0] + w[0]),
    #             -np.sin(d[1] + w[1]),
    #         ]
    #         assert np.allclose(grad2_w_c, expected, atol=0.1)


@pytest.mark.parametrize("dev_name,diff_method,mode", qubit_device_and_diff_method)
class TestJIT:
    """Test JAX JIT integration with the QNode

    Note: JAX JIT is not compatible with the jac_support implementation due to
    the id_tap function being used.
    """

    def test_gradient(self, dev_name, diff_method, mode, tol):
        """Test derivative calculation of a scalar valued QNode"""
        dev = qml.device(dev_name, wires=1)

        if diff_method == "adjoint":
            pytest.xfail(reason="The adjoint method is not using host-callback currently")

        @jax.jit
        @qnode(dev, diff_method=diff_method, interface="jax", mode=mode)
        def circuit(x):
            qml.RY(x[0], wires=0)
            qml.RX(x[1], wires=0)
            return qml.expval(qml.PauliZ(0))

        x = jnp.array([1.0, 2.0])
        res = circuit(x)
        g = jax.grad(circuit)(x)

        a, b = x

        expected_res = np.cos(a) * np.cos(b)
        assert np.allclose(res, expected_res, atol=tol, rtol=0)

        expected_g = [-np.sin(a) * np.cos(b), -np.cos(a) * np.sin(b)]
        assert np.allclose(g, expected_g, atol=tol, rtol=0)

    @pytest.mark.xfail(
        reason="Non-trainable parameters are not being correctly unwrapped by the interface"
    )
    def test_gradient_subset(self, dev_name, diff_method, mode, tol):
        """Test derivative calculation of a scalar valued QNode with respect
        to a subset of arguments"""
        a = jnp.array(0.1)
        b = jnp.array(0.2)

        dev = qml.device(dev_name, wires=1)

        @jax.jit
        @qnode(dev, diff_method=diff_method, interface="jax", mode=mode)
        def circuit(a, b):
            qml.RY(a, wires=0)
            qml.RX(b, wires=0)
            qml.RZ(c, wires=0)
            return qml.expval(qml.PauliZ(0))

        res = jax.grad(circuit, argnums=[0, 1])(a, b, 0.0)

        expected_res = np.cos(a) * np.cos(b)
        assert np.allclose(res, expected_res, atol=tol, rtol=0)

        expected_g = [-np.sin(a) * np.cos(b), -np.cos(a) * np.sin(b)]
        assert np.allclose(g, expected_g, atol=tol, rtol=0)
