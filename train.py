import argparse
import os
import shutil
import time

import torch
import torchvision
import torchvision.transforms as transforms
import torchvision.datasets as datasets
import torchvision.models as models

import torch.nn as nn
import torch.nn.parallel
import torch.backends.cudnn as cudnn
import torch.nn.functional as F

import torch.optim as optim
import torch.utils.data
import torch.utils.data.distributed

from torch.autograd import Variable
import numpy as np
import copy

import resnet as RN
import pyramidnet as PYRM


parser = argparse.ArgumentParser(description='thesis')
parser.add_argument('--net_type', default='pyramidnet', type=str,
                    help='networktype: resnet, and pyamidnet')
parser.add_argument('-j', '--workers', default=4, type=int, metavar='N',
                    help='number of data loading workers (default: 4)')
parser.add_argument('--epochs', default=90, type=int, metavar='N',
                    help='number of total epochs to run')
parser.add_argument('-b', '--batch_size', default=128, type=int,
                    metavar='N', help='mini-batch size (default: 256)')
parser.add_argument('--lr', '--learning-rate', default=0.1, type=float,
                    metavar='LR', help='initial learning rate')
parser.add_argument('--momentum', default=0.9, type=float, metavar='M',
                    help='momentum')
parser.add_argument('--weight-decay', '--wd', default=1e-4, type=float,
                    metavar='W', help='weight decay (default: 1e-4)')
parser.add_argument('--print-freq', '-p', default=100, type=int,
                    metavar='N', help='print frequency (default: 10)')
parser.add_argument('--depth', default=32, type=int,
                    help='depth of the network (default: 32)')
parser.add_argument('--no-bottleneck', dest='bottleneck', action='store_false',
                    help='to use basicblock for CIFAR datasets (default: bottleneck)')
parser.add_argument('--dataset', dest='dataset', default='cifar100', type=str,
                    help='dataset (options: cifar10, cifar100, and imagenet)')
parser.add_argument('--no-verbose', dest='verbose', action='store_false',
                    help='to print the status at every iteration')
parser.add_argument('--alpha', default=300, type=float,
                    help='number of new channel increases per depth (default: 300)')
parser.add_argument('--expname', default='TEST', type=str,
                    help='name of experiment')
parser.add_argument('--beta', default=0, type=float,
                    help='hyperparameter beta')
parser.add_argument('--process', dest='process', default='None', type=str,
                    help='process (options : None, cutout, mixup, cutmix, augmix, divmix, cutmixup, aroundmix, fademixup, softcutout)')
parser.add_argument('--cutout_prob', default=0, type=float,
                    help='cutout probability')
parser.add_argument('--cutout_n_holes', type=int, default=1,
                    help='number of holes to cut out from image')
parser.add_argument('--cutout_length', type=int, default=16,
                    help='length of the holes')
parser.add_argument('--mixup_alpha', default=1., type=float,
                    help='mixup interpolation coefficient (default: 1)')
parser.add_argument('--cutmix_prob', default=0, type=float,
                    help='cutmix probability')
parser.add_argument('--divmix_prob', default=0, type=float,
                    help='divmix probability')
parser.add_argument('--cutmixup_alpha', default=1, type=float,
                    help='cutmixup interpolation coefficient (default: 1)')
parser.add_argument('--cutmixup_prob', default=0, type=float,
                    help='cutmixup probability')
parser.add_argument('--aroundmix_alpha', default=1, type=float,
                    help='aroundmix interpolation coefficient (default: 1)')
parser.add_argument('--aroundmix_prob', default=0, type=float,
                    help='aroundmix probability')
parser.add_argument('--fademixup_alpha', default=1, type=float,
                    help='fademixup interpolation coefficient (default: 1)')
parser.add_argument('--fademixup_prob', default=0, type=float,
                    help='fademixup probability')
parser.add_argument('--softcutout_prob', default=0, type=float,
                    help='softcutout probability')
parser.add_argument('--softcutout_n_holes', type=int, default=1,
                    help='number of holes to cut out from image')
parser.add_argument('--softcutout_length', type=int, default=16,
                    help='length of the holes')
parser.add_argument('--softcutout_alpha', type=float, default=1.0,
                    help='softcutout strength')



parser.set_defaults(bottleneck=True)
parser.set_defaults(verbose=True)

best_err1 = 100
best_err5 = 100


def main():

    global args, best_err1, best_err5

    args = parser.parse_args()

    if args.dataset.startswith('cifar'):
        normalize = transforms.Normalize(mean=[x / 255.0 for x in [125.3, 123.0, 113.9]],
                                            std=[x / 255.0 for x in [63.0, 62.1, 66.7]])

        transform_train = transforms.Compose([
            transforms.RandomCrop(32, padding=4),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            normalize,
        ])
        
        transform_test = transforms.Compose([
            transforms.ToTensor(),
            normalize,
        ])

        if args.dataset == 'cifar100':
            train_loader = torch.utils.data.DataLoader(
                datasets.CIFAR100('../data', train=True, download=True, transform=transform_train),
                batch_size=args.batch_size, shuffle=True, num_workers=args.workers, pin_memory=True)
            val_loader = torch.utils.data.DataLoader(
                datasets.CIFAR100('../data', train=False, transform=transform_test),
                batch_size=args.batch_size, shuffle=True, num_workers=args.workers, pin_memory=True)
            numberofclass = 100
        elif args.dataset == 'cifar10':
            train_loader = torch.utils.data.DataLoader(
                datasets.CIFAR10('../data',train=True, download=True, transform=transform_train),
                batch_size=args.batch_size, shuffle=True, num_workers=args.workers, pin_memory=True)

            val_loader = torch.utils.data.DataLoader(
                        datasets.CIFAR10('../data', train=False, transform=transform_test),
                        batch_size=args.batch_size, shuffle=True, num_workers=args.workers, pin_memory=True)
            numberofclass = 10
        else:
            raise Exception('unknown dataset : {}'.format(args.dataset))

    if args.net_type == 'resnet':
        model = RN.ResNet(args.dataset, args.depth, numberofclass, args.bottleneck)
    elif args.net_type == 'pyramidnet':
        model = PYRM.PyramidNet(args.dataset, args.depth, args.alpha, numberofclass, args.bottleneck)
    else:
        raise Exception('unknown network architecture: {}'.format(args.net_type))


    model = torch.nn.DataParallel(model).cuda()

    #print(model)
    #print('the number of model parameters: {}'.format(sum([p.data.nelement() for p in model.parameters()])))

    criterion = nn.CrossEntropyLoss().cuda()

    optimizer = optim.SGD(model.parameters(), args.lr, momentum=args.momentum, weight_decay=args.weight_decay, nesterov=True)

    cudnn.benchmark = True

    for epoch in range(0, args.epochs):
        
        adjust_learning_rate(optimizer, epoch)

        # train for one epoch
        train_loss = train(train_loader, model, criterion, optimizer, epoch)

        # evaluate on validation set
        err1, err5, val_loss = validate(val_loader, model, criterion, epoch)

        # remember best prec@1 and save checkpoint
        is_best = err1 <= best_err1
        best_err1 = min(err1, best_err1)
        if is_best:
            best_err5 = err5

        print('Current best accuracy (top-1 and 5 error):', best_err1, best_err5)
        save_checkpoint({
            'epoch': epoch,
            'arch': args.net_type,
            'state_dict': model.state_dict(),
            'best_err1': best_err1,
            'best_err5': best_err5,
            'optimizer': optimizer.state_dict(),
        }, is_best)

    print('Best accuracy (top-1 and 5 error):', best_err1, best_err5)


def train(train_loader, model, criterion, optimizer, epoch):
    
    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()
    top1 = AverageMeter()
    top5 = AverageMeter()

    model.train()

    end = time.time()
    current_LR = get_learning_rate(optimizer)[0]

    for i, (input, target) in enumerate(train_loader):
        # measure data loading time
        data_time.update(time.time() - end)

        input = input.cuda()
        target = target.cuda()

        if args.process == 'None':
            # compute output
            output = model(input)
            loss = criterion(output, target)
        elif args.process == 'cutout':
            r = np.random.rand(1)
            if args.beta > 0 and r < args.cutout_prob:
                h = input.size()[2]
                w = input.size()[3]

                mask = np.ones((h, w), np.float32)

                for n in range(args.cutout_n_holes):
                    y = np.random.randint(h)
                    x = np.random.randint(w)

                    y1 = np.clip(y - args.cutout_length // 2, 0, h)
                    y2 = np.clip(y + args.cutout_length // 2, 0, h)
                    x1 = np.clip(x - args.cutout_length // 2, 0, w)
                    x2 = np.clip(x + args.cutout_length // 2, 0, w)

                    mask[y1: y2, x1: x2] = 0.

                mask = torch.from_numpy(mask)
                mask = mask.expand_as(input)
                mask = mask.cuda()
                input = input * mask

                output = model(input)
                loss = criterion(output, target)
            else:
                # compute output
                output = model(input)
                loss = criterion(output, target)    
        elif args.process == 'mixup':
            alpha = args.mixup_alpha
            if alpha > 0:
                lam = np.random.beta(alpha, alpha)
            else:
                lam = 1

            batch_size = input.size()[0]
            index = torch.randperm(batch_size).cuda()

            input = lam * input + (1 - lam) * input[index, :]
            
            target_a = target
            target_b = target[index]

            inputs, targets_a, targets_b = map(Variable, (input, target_a, target_b))
            output = model(input)
            loss = lam * criterion(output, target_a) + (1 - lam) * criterion(output, target_b)

        elif args.process == 'cutmix':
            r = np.random.rand(1)
            if args.beta > 0 and r < args.cutmix_prob:
                # generate mixed sample
                lam = np.random.beta(args.beta, args.beta)
                rand_index = torch.randperm(input.size()[0]).cuda()
                target_a = target
                target_b = target[rand_index]
                bbx1, bby1, bbx2, bby2 = rand_bbox(input.size(), lam)
                input[:, :, bbx1:bbx2, bby1:bby2] = input[rand_index, :, bbx1:bbx2, bby1:bby2]
                # adjust lambda to exactly match pixel ratio
                lam = 1 - ((bbx2 - bbx1) * (bby2 - bby1) / (input.size()[-1] * input.size()[-2]))
                # compute output
                output = model(input)
                loss = criterion(output, target_a) * lam + criterion(output, target_b) * (1. - lam)
            else:
                # compute output
                output = model(input)
                loss = criterion(output, target)
        elif args.process == 'cutmixup':
            r = np.random.rand(1)
            alpha = args.cutmixup_alpha
            if alpha > 0:
                mixuplam = np.random.beta(alpha, alpha)
            else:
                mixuplam = 1

            if args.beta > 0 and r < args.cutmixup_prob:
                # generate mixed sample
                cutmixlam = np.random.beta(args.beta, args.beta)
                rand_index = torch.randperm(input.size()[0]).cuda()
                target_a = target
                target_b = target[rand_index]
                bbx1, bby1, bbx2, bby2 = rand_bbox(input.size(), cutmixlam)
                input[:, :, bbx1:bbx2, bby1:bby2] = mixuplam * input[:, :, bbx1:bbx2, bby1:bby2] + (1-mixuplam) * input[rand_index, :, bbx1:bbx2, bby1:bby2]
                # adjust lambda to exactly match pixel ratio
                cutmixlam = 1 - ((bbx2 - bbx1) * (bby2 - bby1) / (input.size()[-1] * input.size()[-2]))

                inputs, targets_a, targets_b = map(Variable, (input, target_a, target_b))
                # compute output
                output = model(input)
                loss = criterion(output, target_a) * (1. - (1. - cutmixlam) * (1. - mixuplam)) + criterion(output, target_b) * (1. - cutmixlam) * (1. - mixuplam)
            else:
                # compute output
                output = model(input)
                loss = criterion(output, target)
        elif args.process == 'divmix':
            r = np.random.rand(1)
            if r < args.divmix_prob:
                # generate mixed sample
                rand_index1 = torch.randperm(input.size()[0]).cuda()
                rand_index2 = torch.randperm(input.size()[0]).cuda()
                rand_index3 = torch.randperm(input.size()[0]).cuda()
                target_1 = target
                target_2 = target[rand_index1]
                target_3 = target[rand_index2]
                target_4 = target[rand_index3]
                h = input.size()[2]
                w = input.size()[3]
                input[:, :, w//2:w, 0:h//2] = input[rand_index1, :, w//2:w, 0:h//2]
                input[:, :, 0:w//2, h//2:h] = input[rand_index2, :, 0:w//2, h//2:h]
                input[:, :, w//2:w, h//2:h] = input[rand_index3, :, w//2:w, h//2:h]
                # compute output
                output = model(input)
                loss = 0.25 * (criterion(output, target_1) + criterion(output, target_2) + criterion(output, target_3) + criterion(output, target_4) )
            else:
                # compute output
                output = model(input)
                loss = criterion(output, target)
        elif args.process == 'aroundmix':
            alpha = args.aroundmix_alpha
            r = np.random.rand(1)
            if r < args.aroundmix_prob:
                h = input.size()[2]
                w = input.size()[3]

                inputi = copy.deepcopy(input)
                inputi = inputi * (1 - alpha * 8)
                inputi[:,:,0:w-1,:] = inputi[:,:,0:w-1,:] + alpha * input[:,:,1:w,:]
                inputi[:,:,0:w-1,0:h-1] = inputi[:,:,0:w-1,0:h-1] + alpha * input[:,:,1:w,1:h]
                inputi[:,:,:,0:h-1] = inputi[:,:,:,0:h-1] + alpha * input[:,:,:,1:h]
                inputi[:,:,1:w,0:h-1] = inputi[:,:,1:w,0:h-1] + alpha * input[:,:,0:w-1,1:h]
                inputi[:,:,1:w,:] = inputi[:,:,1:w,:] + alpha * input[:,:,0:w-1,:]
                inputi[:,:,1:w,1:h] = inputi[:,:,1:w,1:h] + alpha * input[:,:,0:w-1,0:h-1]
                inputi[:,:,:,1:h] = inputi[:,:,:,1:h] + alpha * input[:,:,:,0:h-1]
                inputi[:,:,0:w-1,1:h] = inputi[:,:,0:w-1,1:h] + alpha * input[:,:,1:w,0:h-1]
                input = inputi

                output = model(input)
                loss = criterion(output, target)
            else :
                output = model(input)
                loss = criterion(output, target)
        elif args.process == 'fademixup':

            alpha = args.fademixup_alpha
            if alpha > 0:
                lam = np.random.beta(alpha, alpha)
            else:
                lam = 1

            batch_size = input.size()[0]
            index = torch.randperm(batch_size).cuda()
            h, w = input.size()[2], input.size()[3]
            shorter = min(h,w)
            lam_unit = lam / ((1/6) * (shorter/2) * (shorter/2 + 1) * (shorter/2 - 4))
            for i in range(shorter//2):
                w_i = (i*w)//shorter
                w_next = ((i+1)*w)//shorter
                h_i = (i*h)//shorter
                h_next = ((i+1)*h)//shorter
                lam_i = i * lam_unit
                input[:,:,w_i:w-w_i,h_i:h-h_i-1] = (1-lam_i) * input[:,:,w_i:w-w_i,h_i:h-h_i-1] + lam_i * input[:,:,w_i:w-w_i,h_i:h-h_i-1]
                input[:,:,w-w_next:w-w_i,h_i+1:h-h_i] = (1-lam_i) * input[:,:,w-w_next:w-w_i,h_i+1:h-h_i] + lam_i * input[:,:,w-w_next:w-w_i,h_i+1:h-h_i]
                input[:,:,w_i+1:w-w_i,h_i:h_next] = (1-lam_i) * input[:,:,w_i+1:w-w_i,h_i:h_next] + lam_i * input[:,:,w_i+1:w-w_i,h_i:h_next]
                input[:,:,w_i:w-w_i-1,h-h_next:h-h_i] = (1-lam_i) * input[:,:,w_i:w-w_i-1,h-h_next:h-h_i] + lam_i * input[:,:,w_i:w-w_i-1,h-h_next:h-h_i]

            target_a = target
            target_b = target[index]

            inputs, targets_a, targets_b = map(Variable, (input, target_a, target_b))
            output = model(input)
            loss = (1-lam) * criterion(output, target_a) + lam * criterion(output, target_b)
        elif args.process == 'softcutout':
            r = np.random.rand(1)
            alpha = args.softcutout_alpha
            if args.beta > 0 and r < args.softcutout_prob:
                h = input.size()[2]
                w = input.size()[3]

                mask = np.ones((h, w), np.float32)

                for n in range(args.cutout_n_holes):
                    y = np.random.randint(h)
                    x = np.random.randint(w)

                    y1 = np.clip(y - args.softcutout_length // 2, 0, h)
                    y2 = np.clip(y + args.softcutout_length // 2, 0, h)
                    x1 = np.clip(x - args.softcutout_length // 2, 0, w)
                    x2 = np.clip(x + args.softcutout_length // 2, 0, w)

                    mask[y1: y2, x1: x2] = alpha

                mask = torch.from_numpy(mask)
                mask = mask.expand_as(input)
                mask = mask.cuda()
                input = input * mask

                output = model(input)
                loss = criterion(output, target)
            else:
                # compute output
                output = model(input)
                loss = criterion(output, target)    
        
        else:
            raise Exception('unknown data augmentation process: {}'.format(args.process))

        # measure accuracy and record loss
        err1, err5 = accuracy(output.data, target, topk=(1,5))

        losses.update(loss.item(), input.size(0))
        top1.update(err1.item(), input.size(0))
        top5.update(err5.item(), input.size(0))

        # compute gradient and do SGD step
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.print_freq == 0 and args.verbose == True:
            print('Epoch: [{0}/{1}][{2}/{3}]\t'
                  'LR: {LR:.6f}\t'
                  'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                  'Data {data_time.val:.3f} ({data_time.avg:.3f})\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Top 1-err {top1.val:.4f} ({top1.avg:.4f})\t'
                  'Top 5-err {top5.val:.4f} ({top5.avg:.4f})'.format(
                epoch, args.epochs, i, len(train_loader), LR=current_LR, batch_time=batch_time,
                data_time=data_time, loss=losses, top1=top1, top5=top5))

    print('* Epoch: [{0}/{1}]\t Top 1-err {top1.avg:.3f}  Top 5-err {top5.avg:.3f}\t Train Loss {loss.avg:.3f}'.format(
        epoch, args.epochs, top1=top1, top5=top5, loss=losses))

    return losses.avg


def rand_bbox(size, lam):
    W = size[2]
    H = size[3]
    cut_rat = np.sqrt(1. - lam)
    cut_w = np.int(W * cut_rat)
    cut_h = np.int(H * cut_rat)

    # uniform
    cx = np.random.randint(W)
    cy = np.random.randint(H)

    bbx1 = np.clip(cx - cut_w // 2, 0, W)
    bby1 = np.clip(cy - cut_h // 2, 0, H)
    bbx2 = np.clip(cx + cut_w // 2, 0, W)
    bby2 = np.clip(cy + cut_h // 2, 0, H)

    return bbx1, bby1, bbx2, bby2


def validate(val_loader, model, criterion, epoch):
    batch_time = AverageMeter()
    losses = AverageMeter()
    top1 = AverageMeter()
    top5 = AverageMeter()

    # switch to evaluate mode
    model.eval()

    end = time.time()
    for i, (input, target) in enumerate(val_loader):
        target = target.cuda()

        output = model(input)
        loss = criterion(output, target)

        # measure accuracy and record loss
        err1, err5 = accuracy(output.data, target, topk=(1, 5))

        losses.update(loss.item(), input.size(0))

        top1.update(err1.item(), input.size(0))
        top5.update(err5.item(), input.size(0))

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.print_freq == 0 and args.verbose == True:
            print('Test (on val set): [{0}/{1}][{2}/{3}]\t'
                  'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Top 1-err {top1.val:.4f} ({top1.avg:.4f})\t'
                  'Top 5-err {top5.val:.4f} ({top5.avg:.4f})'.format(
                epoch, args.epochs, i, len(val_loader), batch_time=batch_time, loss=losses,
                top1=top1, top5=top5))

    print('* Epoch: [{0}/{1}]\t Top 1-err {top1.avg:.3f}  Top 5-err {top5.avg:.3f}\t Test Loss {loss.avg:.3f}'.format(
        epoch, args.epochs, top1=top1, top5=top5, loss=losses))
    return top1.avg, top5.avg, losses.avg


def save_checkpoint(state, is_best, filename='checkpoint.pth.tar'):
    directory = "runs/%s/" % (args.expname)
    if not os.path.exists(directory):
        os.makedirs(directory)
    filename = directory + filename
    torch.save(state, filename)
    if is_best:
        shutil.copyfile(filename, 'runs/%s/' % (args.expname) + 'model_best.pth.tar')


class AverageMeter(object):
    """Computes and stores the average and current value"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count


def adjust_learning_rate(optimizer, epoch):
    """Sets the learning rate to the initial LR decayed by 10 every 30 epochs"""
    if args.dataset.startswith('cifar'):
        lr = args.lr * (0.1 ** (epoch // (args.epochs * 0.5))) * (0.1 ** (epoch // (args.epochs * 0.75)))
    elif args.dataset == ('imagenet'):
        if args.epochs == 300:
            lr = args.lr * (0.1 ** (epoch // 75))
        else:
            lr = args.lr * (0.1 ** (epoch // 30))

    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


def get_learning_rate(optimizer):
    lr = []
    for param_group in optimizer.param_groups:
        lr += [param_group['lr']]
    return lr


def accuracy(output, target, topk=(1,)):
    """Computes the precision@k for the specified values of k"""
    maxk = max(topk)
    batch_size = target.size(0)

    _, pred = output.topk(maxk, 1, True, True)
    pred = pred.t()
    correct = pred.eq(target.view(1, -1).expand_as(pred))

    res = []
    for k in topk:
        #correct_k = correct[:k].view(-1).float().sum(0, keepdim=True)
        correct_k = correct[:k].reshape(-1).float().sum(0, keepdim=True)
        wrong_k = batch_size - correct_k
        res.append(wrong_k.mul_(100.0 / batch_size))

    return res