from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .forms import DraftForm, TaskForm, ProposalForm, EvidenceForm
from .models import Task, Team, Proposal
from .services import grouped_questions, breakdown
from .ai import generate_questions


def catalog(request):
    tasks = Task.objects.filter(published=True)
    query = request.GET.get('q', '').strip()
    if query:
        tasks = tasks.filter(Q(title__icontains=query) | Q(need__icontains=query))
    industry = request.GET.get('industry', '')
    if industry:
        tasks = tasks.filter(industry=industry)
    level = request.GET.get('level', '')
    ranges = {'draft': (0, 39), 'working': (40, 69), 'ready': (70, 89), 'priority': (90, 100)}
    if level in ranges:
        tasks = tasks.filter(score__range=ranges[level])
    return render(request, 'projects/catalog.html', {'tasks': tasks, 'industries': Task.objects.filter(published=True).values_list('industry', flat=True).distinct().order_by('industry'), 'total': Task.objects.filter(published=True).count(), 'team_count': Team.objects.count(), 'proposal_count': Proposal.objects.count(), 'query': query, 'industry': industry, 'level': level})


@login_required
def workspace(request):
    return render(request, 'projects/workspace.html', {'tasks': Task.objects.filter(owner=request.user), 'proposals': Proposal.objects.filter(team__user=request.user).select_related('task', 'team')})


@login_required
def create(request):
    form = DraftForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        task = form.save(commit=False)
        task.owner = request.user
        task.context = task.draft
        task.save()
        return redirect('edit', pk=task.pk)
    return render(request, 'projects/form.html', {'form': form, 'heading': 'Начнём с вашей задачи', 'subtitle': 'Опишите потребность своими словами. Затем уточним детали.', 'button': 'Продолжить →'})


@login_required
def edit(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    questions = grouped_questions(task)
    assistant_source = 'Локальный помощник'
    assistant_notice = 'Ответьте в полях карточки или запросите уточняющие вопросы у OpenAI.'
    form = TaskForm(request.POST or None, instance=task)
    ai_requested = request.method == 'POST' and request.POST.get('action') == 'analyze'
    if ai_requested:
        form.fields['confirm'].required = False
        if form.is_valid():
            analysis = generate_questions(form.instance)
            questions = analysis['questions']
            assistant_source = analysis['source']
            assistant_notice = analysis['notice']
    elif request.method == 'POST' and form.is_valid():
        task = form.save(commit=False)
        task.confirmed = True
        task.score = sum(row['earned'] for row in breakdown(task))
        task.save()
        messages.success(request, 'Карточка подтверждена. Рейтинг пересчитан.')
        return redirect('detail', pk=task.pk)
    field_blocks = [{'field': field, 'questions': [q['text'] for q in questions if q['field'] == field.name]} for field in form]
    return render(request, 'projects/form.html', {'form': form, 'field_blocks': field_blocks, 'task': task, 'questions': questions, 'assistant_source': assistant_source, 'assistant_notice': assistant_notice, 'heading': 'Добавьте ясности — получите баллы', 'subtitle': 'Заполняйте только известные сведения. Каждое подтверждённое дополнение повышает готовность.', 'button': 'Подтвердить и сохранить'})


def detail(request, pk):
    task = get_object_or_404(Task, pk=pk)
    owner = request.user.is_authenticated and task.owner_id == request.user.pk
    if not task.published and not owner:
        return HttpResponseForbidden('Черновик доступен только автору.')
    team = Team.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    proposals = task.proposals.select_related('team') if owner else task.proposals.filter(team=team).select_related('team')
    fields = [(task._meta.get_field(f).verbose_name, getattr(task, f)) for f in ['context', 'need', 'users', 'data', 'constraints', 'result', 'success', 'contact', 'interaction']]
    return render(request, 'projects/detail.html', {'task': task, 'owner': owner, 'team': team, 'rows': breakdown(task), 'fields': fields, 'proposals': proposals, 'form': ProposalForm()})


@login_required
@require_POST
def publish(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    if not task.confirmed:
        return HttpResponseBadRequest('Сначала подтвердите карточку.')
    task.published = True
    task.save(update_fields=['published'])
    messages.success(request, 'Задача опубликована и доступна всем командам.')
    return redirect('detail', pk=pk)


@login_required
def propose(request, pk):
    task = get_object_or_404(Task, pk=pk, published=True)
    team = get_object_or_404(Team, user=request.user)
    if task.owner_id == request.user.pk:
        return HttpResponseForbidden('Нельзя откликнуться на собственную задачу.')
    form = ProposalForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        proposal = form.save(commit=False)
        proposal.task, proposal.team = task, team
        proposal.save()
        messages.success(request, 'Предложение отправлено бизнесу.')
        return redirect('detail', pk=pk)
    return render(request, 'projects/form.html', {'form': form, 'heading': 'Предложить решение', 'subtitle': task.title, 'button': 'Отправить предложение'})


@login_required
@require_POST
@transaction.atomic
def decide(request, pk):
    proposal = get_object_or_404(Proposal.objects.select_for_update(), pk=pk, task__owner=request.user)
    action = request.POST.get('action')
    if action == 'progress' and proposal.status == 'selected' and proposal.evidence.strip():
        proposal.progress_confirmed = True
    elif action in ('selected', 'rejected') and not proposal.progress_confirmed:
        proposal.status = action
    else:
        return HttpResponseBadRequest('Недопустимое действие. Для баллов нужен результат выбранной команды.')
    proposal.save()
    return redirect('detail', pk=proposal.task_id)


@login_required
def evidence(request, pk):
    proposal = get_object_or_404(Proposal, pk=pk, team__user=request.user, status='selected', progress_confirmed=False)
    form = EvidenceForm(request.POST or None, instance=proposal)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Результат этапа передан на подтверждение бизнесу.')
        return redirect('workspace')
    return render(request, 'projects/form.html', {'form': form, 'heading': 'Результат этапа', 'subtitle': proposal.task.title, 'button': 'Передать на подтверждение'})
