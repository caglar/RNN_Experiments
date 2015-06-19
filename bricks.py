from theano import tensor
from theano.ifelse import ifelse

from blocks.bricks import Initializable
from blocks.bricks.base import application, lazy
from blocks.bricks.recurrent import BaseRecurrent, recurrent
from blocks.roles import add_role, WEIGHT, BIAS, INITIAL_STATE
from blocks.utils import (
    check_theano_variable, shared_floatx_nans, shared_floatx_zeros)


class LookupTable(Initializable):

    """Encapsulates representations of a range of integers.
    Parameters
    ----------
    length : int
        The size of the lookup table, or in other words, one plus the
        maximum index for which a representation is contained.
    dim : int
        The dimensionality of representations.
    Notes
    -----
    See :class:`.Initializable` for initialization parameters.
    """
    has_bias = True

    @lazy(allocation=['length', 'dim'])
    def __init__(self, length, dim, **kwargs):
        super(LookupTable, self).__init__(**kwargs)
        self.length = length
        self.dim = dim

    @property
    def W(self):
        return self.params[0]

    @property
    def b(self):
        return self.params[1]

    def _allocate(self):
        W = shared_floatx_nans((self.length, self.dim), name='W')
        self.params.append(W)
        add_role(W, WEIGHT)
        b = shared_floatx_nans((self.dim,), name='W')
        self.params.append(b)
        add_role(b, BIAS)

    def _initialize(self):
        self.weights_init.initialize(self.W, self.rng)
        self.biases_init.initialize(self.b, self.rng)

    @application
    def apply(self, indices):
        """Perform lookup.
        Parameters
        ----------
        indices : :class:`~tensor.TensorVariable`
            The indices of interest. The dtype must be integer.
        Returns
        -------
        output : :class:`~tensor.TensorVariable`
            Representations for the indices of the query. Has :math:`k+1`
            dimensions, where :math:`k` is the number of dimensions of the
            `indices` parameter. The last dimension stands for the
            representation element.
        """
        check_theano_variable(indices, None, "int")
        output_shape = [indices.shape[i]
                        for i in range(indices.ndim)] + [self.dim]
        return self.W[indices.flatten()].reshape(output_shape) + self.b


class ClockworkBase(BaseRecurrent, Initializable):

    @lazy(allocation=['dim'])
    def __init__(self, dim, period, activation, **kwargs):
        super(ClockworkBase, self).__init__(**kwargs)
        self.dim = dim
        self.period = period
        self.children = [activation]

    @property
    def W(self):
        return self.params[0]

    def get_dim(self, name):
        if name == 'mask':
            return 0
        if name in (ClockworkBase.apply.sequences +
                    ClockworkBase.apply.states):
            return self.dim
        return super(ClockworkBase, self).get_dim(name)

    def _allocate(self):
        self.params.append(shared_floatx_nans((self.dim, self.dim), name="W"))
        add_role(self.params[0], WEIGHT)
        self.params.append(shared_floatx_zeros((self.dim,),
                                               name="initial_state"))
        add_role(self.params[1], INITIAL_STATE)

        self.params.append(shared_floatx_zeros((1,), name="initial_time"))
        add_role(self.params[2], INITIAL_STATE)

    def _initialize(self):
        self.weights_init.initialize(self.W, self.rng)

    @recurrent(sequences=['inputs', 'mask'], states=['states', 'time'],
               outputs=['states', 'time'], contexts=[])
    def apply(self, inputs=None, states=None, time=None, mask=None):
        """Apply the simple transition.
        Parameters
        ----------
        inputs : :class:`~tensor.TensorVariable`
            The 2D inputs, in the shape (batch, features).
        states : :class:`~tensor.TensorVariable`
            The 2D states, in the shape (batch, features).
        mask : :class:`~tensor.TensorVariable`
            A 1D binary array in the shape (batch,) which is 1 if
            there is data available, 0 if not. Assumed to be 1-s
            only if not given.
        time : :class:`~tensor.TensorVariable`
            A number representing the time steps currently computed
        """
        next_states = ifelse(tensor.eq(time[0, 0] % self.period, 0),
                             self.children[0].apply(
                                 inputs + tensor.dot(states, self.W)),
                             states)

        if mask:
            next_states = (mask[:, None] * next_states +
                           (1 - mask[:, None]) * states)

        return next_states, time + 1

    @application(outputs=apply.states)
    def initial_states(self, batch_size, *args, **kwargs):
        return [tensor.repeat(self.params[1][None, :], batch_size, 0),
                self.params[2][None, :]]
