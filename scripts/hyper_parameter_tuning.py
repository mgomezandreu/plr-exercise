from __future__ import print_function
import argparse
import torch
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, transforms
from torch.optim.lr_scheduler import StepLR
import wandb
import types

import optuna

from plr_exercise.models.cnn import Net


def train(args, model, device, train_loader, optimizer, epoch):
    """ Train a model for one epoch.
    
    Arguments:
    args            -- Hyperparameters of the model
    model           -- pytorch model object used for training
    device          -- device on which to train on
    train_loader    -- data loader for training data
    optimizer       -- optimizer to be used
    epoch           -- number of current epoch
    """
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):

        data, target = data.to(device), target.to(device)
        optimizer.zero_grad()
        output = model(data)
        loss = F.nll_loss(output, target)
        loss.backward()
        optimizer.step()
        if batch_idx % args.log_interval == 0:
            print(
                "Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}".format(
                    epoch,
                    batch_idx * len(data),
                    len(train_loader.dataset),
                    100.0 * batch_idx / len(train_loader),
                    loss.item(),
                )
            )
            if args.dry_run:
                break

    train_loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in train_loader:

            data, target = data.to(device), target.to(device)
            output = model(data)
            train_loss += F.nll_loss(output, target, reduction="sum").item()  # sum up batch loss
            pred = output.argmax(dim=1, keepdim=True)  # get the index of the max log-probability
            correct += pred.eq(target.view_as(pred)).sum().item()

    train_loss /= len(train_loader.dataset)

    wandb.log({"train_loss": train_loss}) 


def test(model, device, test_loader, epoch):
    """ Test the model on test data and return the test_loss.

    Arguments:
    model           -- pytorch model object to be tested
    device          -- device on which to train
    test_loader     -- data loader for test data
    epoch           -- number of current epoch
    """

    model.eval()
    test_loss = 0
    correct = 0

    with torch.no_grad():
        for data, target in test_loader:

            data, target = data.to(device), target.to(device)
            output = model(data)
            test_loss += F.nll_loss(output, target, reduction="sum").item()  # sum up batch loss
            pred = output.argmax(dim=1, keepdim=True)  # get the index of the max log-probability
            correct += pred.eq(target.view_as(pred)).sum().item()

    test_loss /= len(test_loader.dataset)

    print(
        "\nTest set: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)\n".format(
            test_loss, correct, len(test_loader.dataset), 100.0 * correct / len(test_loader.dataset)
        )
    )

    wandb.log({"test_loss": test_loss})   

    return test_loss


def objective(trial):
    """Run training and testing process for parameters specified in trial and return the final test loss."""
    args = types.SimpleNamespace()
    args.batch_size = 64
    args.test_batch_size = 1000
    args.epochs = trial.suggest_int("epochs", 3 , 30)
    args.lr = trial.suggest_float("learning_rate", 0, 1)
    args.gamma = 0.7
    args.no_cuda = False
    args.dry_run = False
    args.seed = 1
    args.log_interval = 10
    args.save_model = False

    use_cuda = not args.no_cuda and torch.cuda.is_available()

    torch.manual_seed(args.seed)

    if use_cuda:
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")

    train_kwargs = {"batch_size": args.batch_size}
    test_kwargs = {"batch_size": args.test_batch_size}
    if use_cuda:
        cuda_kwargs = {"num_workers": 1, "pin_memory": True, "shuffle": True}
        train_kwargs.update(cuda_kwargs)
        test_kwargs.update(cuda_kwargs)

    transform = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))])
    dataset1 = datasets.MNIST("../data", train=True, download=True, transform=transform)
    dataset2 = datasets.MNIST("../data", train=False, transform=transform)
    train_loader = torch.utils.data.DataLoader(dataset1, **train_kwargs)
    test_loader = torch.utils.data.DataLoader(dataset2, **test_kwargs)

    model = Net().to(device)
    optimizer = optim.Adam(model.parameters(), lr=args.lr)

    wandb.init(
        project="plr_exercise",
        config={
            "learning_rate": args.lr,
            "architecture": "CNN",
            "dataset": "MNIST",
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "gamma": args.gamma,
            "seed": args.seed,
        },
    )

    wandb.run.log_code(__file__ + "/..")

    test_loss = 1000000

    scheduler = StepLR(optimizer, step_size=1, gamma=args.gamma)
    for epoch in range(args.epochs):
        train(args, model, device, train_loader, optimizer, epoch)
        test_loss = test(model, device, test_loader, epoch)
        scheduler.step()

    wandb.finish()

    if args.save_model:
        torch.save(model.state_dict(), "mnist_cnn.pt")

    return test_loss



if __name__ == "__main__":
    study = optuna.create_study()
    study.optimize(objective, n_trials=100)

    print(study.best_params)

