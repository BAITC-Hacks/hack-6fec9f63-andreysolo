from django import forms
from .models import Task, Proposal


class DraftForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['title', 'industry', 'draft']
        widgets = {'draft': forms.Textarea(attrs={'rows': 5, 'placeholder': 'Например: теряем заявки клиентов между мессенджерами…'})}


class TaskForm(forms.ModelForm):
    confirm = forms.BooleanField(label='Подтверждаю достоверность заполненных сведений')

    class Meta:
        model = Task
        fields = ['title', 'industry', 'context', 'need', 'users', 'data', 'constraints', 'result', 'success', 'contact', 'interaction']
        widgets = {f: forms.Textarea(attrs={'rows': 3}) for f in fields if f not in ('title', 'industry', 'contact')}


class ProposalForm(forms.ModelForm):
    class Meta:
        model = Proposal
        fields = ['idea', 'plan', 'duration', 'prototype']
        widgets = {'idea': forms.Textarea(attrs={'rows': 3}), 'plan': forms.Textarea(attrs={'rows': 3})}


class EvidenceForm(forms.ModelForm):
    class Meta:
        model = Proposal
        fields = ['evidence']
        widgets = {'evidence': forms.Textarea(attrs={'rows': 3})}

    def clean_evidence(self):
        value = self.cleaned_data['evidence'].strip()
        if not value:
            raise forms.ValidationError('Опишите выполненную работу или укажите ссылку.')
        return value
