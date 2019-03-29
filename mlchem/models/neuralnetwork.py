import time
import datetime
import torch

from collections import OrderedDict
from mlchem.data.visualization import parity
from mlchem.models.loss import RMSELoss
from mlchem.utils import convert_elapsed_time

torch.set_printoptions(precision=10)


class NeuralNetwork(torch.nn.Module):
    """Neural Network Regression with Pytorch

    Parameters
    ----------
    hiddenlayers : tuple
        Structure of hidden layers in the neural network.
    activation : str
        The activation function.
    """

    NAME = 'PytorchPotentials'

    @classmethod
    def name(cls):
        """Returns name of class"""

        return cls.NAME

    def __init__(self, hiddenlayers=(3, 3), activation='relu'):
        super(NeuralNetwork, self).__init__()
        self.hiddenlayers = hiddenlayers
        self.activation = activation

    def prepare_model(self, input_dimension, data=None, purpose='training'):
        """Prepare the model

        Parameters
        ----------
        input_dimension : int
            Input's dimension.
        data : object
            DataSet object created from the handler.
        purpose : str
            Purpose of this model: 'training', 'inference'.
        """
        activation = {'tanh': torch.nn.Tanh, 'relu': torch.nn.ReLU,
                      'celu': torch.nn.CELU}

        hl = len(self.hiddenlayers)
        if purpose == 'training':
            print()
            print('Model Training')
            print('==============')
            print('Model name: {}.'.format(self.name()))
            print('Number of hidden-layers: {}' .format(hl))
            print('Structure of Neural Net: {}'
                  .format('(input, ' + str(self.hiddenlayers)[1:-1] +
                          ', output)'))
        layers = range(len(self.hiddenlayers) + 1)
        unique_element_symbols = data.unique_element_symbols[purpose]

        symbol_model_pair = []

        for symbol in unique_element_symbols:
            linears = []

            intercept_name = 'intercept_' + symbol
            slope_name = 'slope_' + symbol

            if purpose == 'training':
                intercept = (data.max_energy + data.min_energy) / 2.
                intercept = torch.nn.Parameter(torch.tensor(intercept,
                                                            requires_grad=True))

                slope = (data.max_energy - data.min_energy) / 2.
                slope = torch.nn.Parameter(torch.tensor(slope,
                                                        requires_grad=True))

                print(intercept, slope)

                self.register_parameter(intercept_name, intercept)
                self.register_parameter(slope_name, slope)
            elif purpose == 'inference':
                intercept = torch.nn.Parameter(torch.tensor(0.))
                slope = torch.nn.Parameter(torch.tensor(0.))
                self.register_parameter(intercept_name, intercept)
                self.register_parameter(slope_name, slope)

            for index in layers:
                # This is the input layer
                if index == 0:
                    out_dimension = self.hiddenlayers[0]
                    _linear = torch.nn.Linear(input_dimension,
                                              out_dimension)
                    linears.append(_linear)
                    linears.append(activation[self.activation]())
                # This is the output layer
                elif index == len(self.hiddenlayers):
                    inp_dimension = self.hiddenlayers[index - 1]
                    out_dimension = 1
                    _linear = torch.nn.Linear(inp_dimension, out_dimension)
                    linears.append(_linear)
                # These are hidden-layers
                else:
                    inp_dimension = self.hiddenlayers[index - 1]
                    out_dimension = self.hiddenlayers[index]
                    _linear = torch.nn.Linear(inp_dimension, out_dimension)
                    linears.append(_linear)
                    linears.append(activation[self.activation]())

            # Stacking up the layers.
            linears = torch.nn.Sequential(*linears)
            symbol_model_pair.append([symbol, linears])

        self.linears = torch.nn.ModuleDict(symbol_model_pair)

        if purpose == 'training':
            print(self.linears)
            # Iterate over all modules and just intialize those that are
            # a linear layer.
            for m in self.modules():
                if isinstance(m, torch.nn.Linear):
                    # nn.init.normal_(m.weight)   # , mean=0, std=0.01)
                    torch.nn.init.xavier_uniform_(m.weight)

    def forward(self, X):
        """Forward propagation

        This is forward propagation and it returns the atomic energy.

        Parameters
        ----------
        X : list
            List of inputs in the feature space.

        Returns
        -------
        outputs : tensor
            A list of tensors with energies per image.
        """

        outputs = []

        for hash in X:
            image = X[hash]
            atomic_energies = []

            for symbol, x in image:
                x = self.linears[symbol](x)

                intercept_name = 'intercept_' + symbol
                slope_name = 'slope_' + symbol
                slope = getattr(self, slope_name)
                intercept = getattr(self, intercept_name)

                x = (slope * x) + intercept
                atomic_energies.append(x)

            atomic_energies = torch.cat(atomic_energies)
            image_energy = torch.sum(atomic_energies)
            outputs.append(image_energy)
        outputs = torch.stack(outputs)
        return outputs


def train(inputs, targets, model=None, data=None, optimizer=None, lr=None,
          weight_decay=None, regularization=None, epochs=100, convergence=None,
          lossfxn=None, device='cpu'):
    """Train the model

    Parameters
    ----------
    inputs : dict
        Dictionary with hashed feature space.
    epochs : int
        Number of full training cycles.
    targets : list
        The expected values that the model has to learn aka y.
    model : object
        The NeuralNetwork class.
    data : object
        DataSet object created from the handler.
    lr : float
        Learning rate.
    weight_decay : float
        Weight decay passed to the optimizer. Default is 0.
    regularization : float
        This is the L2 regularization. It is not the same as weight decay.
    convergence : dict
        Instead of using epochs, users can set a convergence criterion.
    lossfxn : obj
        A loss function object.
    device : str
        Calculation can be run in the cpu or cuda (gpu).
    """

    initial_time = time.time()

    # old_state_dict = {}

    # for key in model.state_dict():
    #     old_state_dict[key] = model.state_dict()[key].clone()

    targets = torch.tensor(targets, requires_grad=False)

    if device == 'cuda':
        print('Moving data to CUDA...')
        targets = targets.cuda()
        _inputs = OrderedDict()
        for hash, f in inputs.items():
            _inputs[hash] = []
            for features in f:
                symbol, vector = features
                _inputs[hash].append((symbol, vector.cuda()))

        inputs = _inputs

        move_time = time.time() - initial_time
        h, m, s = convert_elapsed_time(move_time)
        print('Data moved to GPU in {} hours {} minutes {:.2f} seconds.'
              .format(h, m, s))

    # Define optimizer
    if optimizer is None:
        optimizer = torch.optim.Adam(model.parameters(), lr=lr,
                                     weight_decay=weight_decay)

    print()
    print('{:6s} {:19s} {:12s} {:9s}'.format('Epoch',
                                             'Time Stamp',
                                             'Loss',
                                             'RMSE/atom'))
    print('{:6s} {:19s} {:12s} {:9s}'.format('------',
                                             '-------------------',
                                             '------------',
                                             '---------'))

    _loss = []
    _rmse = []
    epoch = 0

    while True:
        epoch += 1

        outputs = model(inputs)

        if lossfxn is None:
            loss, rmse = RMSELoss(outputs, targets, optimizer, data,
                                  device=device)
        else:
            raise('I do not know what to do')

        _loss.append(loss.item())
        _rmse.append(rmse)

        ts = time.time()
        ts = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d '
                                                          '%H:%M:%S')
        print('{:6d} {} {:8e} {:8f}' .format(epoch, ts, loss, rmse))

        if convergence is None and epoch == epochs:
            break
        elif (convergence is not None and rmse < convergence['energy']):
            break

    training_time = time.time() - initial_time

    h, m, s = convert_elapsed_time(training_time)
    print('Training finished in {} hours {} minutes {:.2f} seconds.'
          .format(h, m, s))
    print('outputs')
    print(outputs)
    print('targets')
    print(targets)

    import matplotlib.pyplot as plt
    plt.plot(list(range(epoch)), _loss, label='loss')
    plt.plot(list(range(epoch)), _rmse, label='rmse/atom')
    plt.legend(loc='upper left')
    plt.show()

    parity(outputs.detach().numpy(), targets.detach().numpy())
