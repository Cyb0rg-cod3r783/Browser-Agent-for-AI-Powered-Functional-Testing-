from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class Page(Base):
    __tablename__ = 'pages'
    id         = Column(Integer, primary_key=True, index=True)
    url        = Column(String(768), nullable=False, unique=True)
    title      = Column(String(255))
    elements   = relationship("Element", back_populates="page")


class Element(Base):
    __tablename__ = 'elements'
    id           = Column(Integer, primary_key=True, index=True)
    page_id      = Column(Integer, ForeignKey('pages.id'), nullable=True)
    element_type = Column(String(50))   # button | input | a | select | ...
    text         = Column(Text)
    selector     = Column(Text)         # CSS selector used by Playwright to find it
    attributes   = Column(Text)         # JSON blob of id/class/name/href/etc.
    page         = relationship("Page", back_populates="elements")
    workflow_steps = relationship("WorkflowStep", back_populates="element")


class Workflow(Base):
    __tablename__ = 'workflows'
    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(255), nullable=False)          # no longer UNIQUE
    url        = Column(String(768), nullable=False)          # starting URL
    created_at = Column(DateTime, default=datetime.utcnow)
    steps      = relationship("WorkflowStep", back_populates="workflow",
                              cascade="all, delete-orphan",
                              order_by="WorkflowStep.step_order")


class WorkflowStep(Base):
    __tablename__ = 'workflow_steps'
    id          = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey('workflows.id'))
    element_id  = Column(Integer, ForeignKey('elements.id'), nullable=True)
    step_order  = Column(Integer, nullable=False)
    action      = Column(String(50))    # click | type | navigate | select | scroll
    value       = Column(Text, nullable=True)   # typed text / selected value / URL
    selector    = Column(Text, nullable=True)   # CSS selector snapshot at record time
    url         = Column(String(768), nullable=True)  # page URL at the time of step
    workflow    = relationship("Workflow", back_populates="steps")
    element     = relationship("Element", back_populates="workflow_steps")
