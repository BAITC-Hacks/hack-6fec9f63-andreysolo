from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .forms import DraftForm, TaskForm, ProposalForm, EvidenceForm
from .models import Task, Team, Proposal, Account
from .roles import role_required, user_role
from .services import grouped_questions, breakdown
from .ai import generate_questions
from .quality import assess_quality, baseline, QUALITY_VERSION


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


@role_required(Account.Role.BUSINESS)
def create(request):
    form = DraftForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        task = form.save(commit=False)
        task.owner = request.user
        task.context = task.draft
        task.save()
        return redirect('edit', pk=task.pk)
    return render(request, 'projects/form.html', {'form': form, 'heading': 'Начнём с вашей задачи', 'subtitle': 'Опишите потребность своими словами. Затем уточним детали.', 'button': 'Продолжить →'})


@role_required(Account.Role.BUSINESS)
def edit(request, pk):
    from .wizard import STEPS, step_form
    from .question_scopes import SCOPE_VERSION
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    key = f'task_wizard_{pk}'
    state = request.session.get(key)
    if not state:
        state = {'step': 0, 'values': {name: getattr(task, name) for name in TaskForm.Meta.fields}, 'analysis': None}
    if state.get('scope_version') != SCOPE_VERSION:
        state.update(analysis=None, scope_version=SCOPE_VERSION)
    state.setdefault('quality_reviews', dict(task.quality_reviews))
    state.setdefault('question_history', {})
    state.setdefault('question_initial_values', {})
    if state.get('quality_version') != QUALITY_VERSION:
        state.update(analysis=None, quality_version=QUALITY_VERSION)
    index = state['step']
    action = request.POST.get('action', '')
    if request.method == 'POST' and request.POST.get('step') != str(index):
        messages.info(request, 'Этот шаг уже изменился. Продолжите с текущего блока.')
        return redirect('edit', pk=pk)
    if index == len(STEPS):
        if request.method == 'POST' and action == 'back':
            state.update(step=index - 1, analysis=None)
            request.session[key] = state
            return redirect('edit', pk=pk)
        data = {**state['values'], 'confirm': request.POST.get('confirm', '')}
        form = TaskForm(data if request.method == 'POST' else None, initial=state['values'], instance=task)
        if request.method == 'POST' and action == 'save' and form.is_valid():
            task = form.save(commit=False)
            task.confirmed = True
            task.quality_reviews = state['quality_reviews']
            task.score = sum(row['earned'] for row in breakdown(task))
            task.save()
            del request.session[key]
            messages.success(request, 'Карточка подтверждена. Рейтинг пересчитан.')
            return redirect('detail', pk=pk)
        for name, value in state['values'].items():
            setattr(task, name, value)
        task.confirmed = True
        task.quality_reviews = state['quality_reviews']
        preview_rows = breakdown(task)
        return render(request, 'projects/wizard.html', {'rating_rows': preview_rows, 'preview_score': sum(row['earned'] for row in preview_rows), 'task': task, 'form': form, 'review': True, 'index': index, 'steps': STEPS, 'summary': [(Task._meta.get_field(name).verbose_name, value) for name, value in state['values'].items()]})
    form = step_form(index, request.POST if request.method == 'POST' else None, state['values'])
    if request.method == 'POST' and form.is_valid():
        state['values'].update(form.cleaned_data)
        for name, value in state['values'].items():
            setattr(task, name, value)
        fields = STEPS[index][1]
        history_key = str(index)
        history = state['question_history'].setdefault(history_key, [])
        for field in fields:
            for question in state['quality_reviews'].get(field, {}).get('questions', []):
                item = {'field': field, 'text': question['text']}
                if item not in history:
                    history.append(item)
        if action == 'back' and index > 0:
            state.update(step=index - 1, analysis=None)
        elif action == 'continue' and state['analysis']:
            unchanged = state['question_initial_values'].get(history_key) == {name: state['values'][name] for name in fields}
            if unchanged and state['analysis']['questions']:
                reviews = baseline(task, fields)
                for name in fields:
                    pending = [q for q in history if q['field'] == name]
                    if pending:
                        reviews[name].update(reason=f'Продолжили без дополнений: осталось уточнений — {len(pending)}.', questions=[{'text': q['text'], 'resolved': False} for q in pending])
                # Fields without questions still need a quality check before full marks.
                remaining = [name for name in fields if not any(q['field'] == name for q in history)]
                if remaining:
                    reviews.update(assess_quality(task, remaining, []))
            else:
                reviews = assess_quality(task, fields, history)
            state['quality_reviews'].update(reviews)
            if any(r['source'] != 'openai' for r in reviews.values()):
                messages.info(request, 'Без подтверждённого устранения уточнений начисляются только базовые баллы за заполнение.')
            state.update(step=index + 1, analysis=None)
        elif action in ('next', 'analyze'):
            for name, value in state['values'].items():
                setattr(task, name, value)
            state['analysis'] = generate_questions(task, focus_fields=fields)
            state['analyzed_values'] = {name: state['values'][name] for name in fields}
            if state['analysis']['source'] == 'OpenAI':
                if state['analysis']['questions'] and not history:
                    state['question_initial_values'][history_key] = dict(state['analyzed_values'])
                for question in state['analysis']['questions']:
                    if question not in history:
                        history.append(question)
        request.session[key] = state
        return redirect('edit', pk=pk)
    request.session[key] = state
    analysis = state['analysis']
    questions = analysis['questions'] if analysis else []
    blocks = [{'field': field, 'questions': [q['text'] for q in questions if q['field'] == field.name]} for field in form]
    return render(request, 'projects/wizard.html', {'task': task, 'form': form, 'field_blocks': blocks, 'analysis': analysis, 'index': index, 'number': index + 1, 'step_title': STEPS[index][0], 'steps': STEPS, 'progress': round(index / len(STEPS) * 100)})


def detail(request, pk):
    task = get_object_or_404(Task, pk=pk)
    role = user_role(request.user)
    owner = role == Account.Role.BUSINESS and task.owner_id == request.user.pk
    if not task.published and not owner:
        return HttpResponseForbidden('Черновик доступен только автору.')
    team = Team.objects.filter(user=request.user).first() if role == Account.Role.STUDENT else None
    proposals = task.proposals.select_related('team') if owner else task.proposals.filter(team=team).select_related('team')
    fields = [(task._meta.get_field(f).verbose_name, getattr(task, f)) for f in ['context', 'need', 'users', 'data', 'constraints', 'result', 'success', 'contact', 'interaction']]
    return render(request, 'projects/detail.html', {'task': task, 'owner': owner, 'team': team, 'rows': breakdown(task), 'fields': fields, 'proposals': proposals, 'form': ProposalForm()})


@role_required(Account.Role.BUSINESS)
@require_POST
def publish(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    if not task.confirmed:
        return HttpResponseBadRequest('Сначала подтвердите карточку.')
    task.published = True
    task.save(update_fields=['published'])
    messages.success(request, 'Задача опубликована и доступна всем командам.')
    return redirect('detail', pk=pk)


@role_required(Account.Role.STUDENT)
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


@role_required(Account.Role.BUSINESS)
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
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'error': 'Действие недоступно. Обновите карточку: для подтверждения этапа нужен результат выбранной команды.'}, status=400)
        return HttpResponseBadRequest('Недопустимое действие. Для баллов нужен результат выбранной команды.')
    proposal.save()
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'id': proposal.pk, 'status': proposal.status, 'status_label': proposal.get_status_display(), 'progress_confirmed': proposal.progress_confirmed, 'can_confirm_progress': proposal.status == 'selected' and bool(proposal.evidence.strip()) and not proposal.progress_confirmed})
    return redirect('detail', pk=proposal.task_id)


@role_required(Account.Role.STUDENT)
def evidence(request, pk):
    proposal = get_object_or_404(Proposal, pk=pk, team__user=request.user, status='selected', progress_confirmed=False)
    form = EvidenceForm(request.POST or None, instance=proposal)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Результат этапа передан на подтверждение бизнесу.')
        return redirect('workspace')
    return render(request, 'projects/form.html', {'form': form, 'heading': 'Результат этапа', 'subtitle': proposal.task.title, 'button': 'Передать на подтверждение'})
